import os
import subprocess
import requests
import base64
import json
import inquirer
from urllib.parse import urlparse
from tqdm import tqdm
from multiprocessing import Pool

# Constants
GITHUB_API_URL = "https://api.github.com"
DEFAULT_EXCLUSIONS = ['.git', 'node_modules']
SUPPORTED_FILETYPES = ['.py', '.ipynb', '.html', '.css', '.js', '.jsx', '.md', '.rst']

# Helper functions
def parse_github_url(url):
    parsed_url = urlparse(url)
    path_segments = parsed_url.path.strip("/").split("/")
    if len(path_segments) >= 2:
        return path_segments[0], path_segments[1]
    raise ValueError("Invalid GitHub URL provided!")

def fetch_repo_content(url, token=None, cache_dir='.cache', per_page=100):
    cache_file = os.path.join(cache_dir, f"{url.replace('/', '_')}.json")
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as file:
            return json.load(file)
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    all_items = []
    page = 1
    while True:
        paginated_url = f"{url}?per_page={per_page}&page={page}"
        response = requests.get(paginated_url, headers=headers)
        response.raise_for_status()
        items = response.json()
        all_items.extend(items)
        if len(items) < per_page:
            break
        page += 1
    
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_file, 'w') as file:
        json.dump(all_items, file)
    
    return all_items

def check_if_git_repo():
    return os.path.isdir('.git')

def extract_git_url():
    result = subprocess.run(['git', 'config', '--get', 'remote.origin.url'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def get_folder_files(folder_path, exclusions):
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if os.path.join(root, d) not in exclusions]
        for file in files:
            if any(file.endswith(ext) for ext in SUPPORTED_FILETYPES):
                yield os.path.join(root, file)

def get_file_content(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def process_file(file_path):
    content = get_file_content(file_path)
    return f"\n{file_path}:\n```\n{content}\n```\n"

def process_folder(folder_path, exclusions):
    file_paths = list(get_folder_files(folder_path, exclusions))
    with Pool() as pool:
        file_contents = list(tqdm(pool.imap(process_file, file_paths), total=len(file_paths)))
    return ''.join(file_contents)

def process_github_repo(owner, repo, token=None, cache_dir='.cache'):
    formatted_string = ""
    
    try:
        readme_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/README.md"
        readme_info = fetch_repo_content(readme_url, token, cache_dir)
        readme_content = base64.b64decode(readme_info['content']).decode('utf-8')
        formatted_string = f"README.md:\n```\n{readme_content}\n```\n\n"
    except requests.exceptions.RequestException:
        formatted_string = "README.md: Not found or error fetching README\n\n"
    
    default_branch = "main"  # or another branch name if different
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    tree_info = fetch_repo_content(url, token, cache_dir)
    
    # Compare the current tree with the cached tree
    cache_file = os.path.join(cache_dir, f"{owner}_{repo}_tree.json")
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as file:
            cached_tree_info = json.load(file)
        if cached_tree_info['sha'] == tree_info['sha']:
            # No changes since the last run
            return formatted_string
    
    # Process the changes and update the cache
    file_paths = []
    for item in tree_info['tree']:
        if item['type'] == 'blob' and any(item['path'].endswith(ext) for ext in SUPPORTED_FILETYPES):
            file_paths.append(item['path'])
    
    def load_file_content(path):
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}"
        file_info = fetch_repo_content(url, token, cache_dir)
        return base64.b64decode(file_info['content']).decode('utf-8')
    
    for path in tqdm(file_paths):
        formatted_string += f"\n{path}:\n```\n{load_file_content(path)}\n```\n"
    
    with open(cache_file, 'w') as file:
        json.dump(tree_info, file)
    
    return formatted_string

def main():
    questions = [
        inquirer.List('mode',
            message="Select execution mode:",
            choices=['GitHub Auto', 'GitHub URL', 'Folder Scan'],
        ),
    ]
    answers = inquirer.prompt(questions)
    
    if answers['mode'] == 'GitHub Auto':
        if check_if_git_repo():
            git_url = extract_git_url()
            if git_url:
                owner, repo = parse_github_url(git_url)
                token = os.environ.get('GITHUB_ACCESS_TOKEN')
                formatted_repo_info = process_github_repo(owner, repo, token)
                output_file_name = f"{repo}-formatted-prompt.txt"
                with open(output_file_name, 'w', encoding='utf-8') as file:
                    file.write(formatted_repo_info)
                print(f"Repository information has been saved to {output_file_name}")
            else:
                print("GitHub URL could not be extracted.")
        else:
            print("Not a valid git repository.")
    
    elif answers['mode'] == 'GitHub URL':
        git_url = input("Enter the GitHub URL: ")
        try:
            owner, repo = parse_github_url(git_url)
            token = os.environ.get('GITHUB_ACCESS_TOKEN')
            formatted_repo_info = process_github_repo(owner, repo, token)
            output_file_name = f"{repo}-formatted-prompt.txt"
            with open(output_file_name, 'w', encoding='utf-8') as file:
                file.write(formatted_repo_info)
            print(f"Repository information has been saved to {output_file_name}")
        except ValueError as e:
            print(e)
    
    elif answers['mode'] == 'Folder Scan':
        folder_questions = [
            inquirer.List('folder_option',
                message="Select folder option:",
                choices=['Current Folder', 'Enter Folder Path'],
            ),
        ]
        folder_answers = inquirer.prompt(folder_questions)
        
        if folder_answers['folder_option'] == 'Current Folder':
            folder_path = os.getcwd()
        else:
            folder_path = input("Enter the folder path: ")
        
        exclusions = input("Enter directories to exclude (comma-separated): ").split(',')
        exclusions = [os.path.join(folder_path, e.strip()) for e in exclusions]
        formatted_folder_info = process_folder(folder_path, exclusions)
        output_file_name = "folder-formatted-prompt.txt"
        with open(output_file_name, 'w', encoding='utf-8') as file:
            file.write(formatted_folder_info)
        print(f"Folder information has been saved to {output_file_name}")

if __name__ == "__main__":
    main()
