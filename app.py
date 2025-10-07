import streamlit as st
import os
from pathlib import Path
import json
import requests
import base64
from groq import Groq
import tempfile
import shutil
from dotenv import load_dotenv
load_dotenv()
# Page config
st.set_page_config(
    page_title="AI README Generator",
    page_icon="🤖",
    layout="wide"
)

DEFAULT_GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def fetch_github_repo_structure(github_url, github_token=None):
    """Fetch repository structure from GitHub API"""
    try:
        # Parse GitHub URL
        parts = github_url.replace('https://github.com/', '').replace('http://github.com/', '').strip('/')
        if '/' not in parts:
            return None, "Invalid GitHub URL format"
        
        owner, repo = parts.split('/')[:2]
        
        # GitHub API endpoints
        api_base = f"https://api.github.com/repos/{owner}/{repo}"
        
        headers = {}
        if github_token:
            headers['Authorization'] = f'token {github_token}'
        
        # Get repository info
        repo_response = requests.get(api_base, headers=headers)
        if repo_response.status_code != 200:
            return None, f"Error: {repo_response.status_code} - {repo_response.json().get('message', 'Unknown error')}"
        
        repo_data = repo_response.json()
        
        # Get repository tree
        tree_url = f"{api_base}/git/trees/{repo_data['default_branch']}?recursive=1"
        tree_response = requests.get(tree_url, headers=headers)
        
        if tree_response.status_code != 200:
            return None, f"Error fetching tree: {tree_response.status_code}"
        
        tree_data = tree_response.json()
        
        analysis = {
            'name': repo_data['name'],
            'description': repo_data.get('description', 'No description'),
            'language': repo_data.get('language', 'Unknown'),
            'stars': repo_data.get('stargazers_count', 0),
            'forks': repo_data.get('forks_count', 0),
            'open_issues': repo_data.get('open_issues_count', 0),
            'topics': repo_data.get('topics', []),
            'files': [],
            'directories': [],
            'languages': {},
            'file_count': 0,
            'has_requirements': False,
            'has_package_json': False,
            'has_dockerfile': False,
            'has_tests': False,
            'config_files': [],
            'owner': owner,
            'repo_url': github_url
        }
        
        for item in tree_data.get('tree', []):
            if item['type'] == 'blob':
                analysis['file_count'] += 1
                path = item['path']
                ext = Path(path).suffix.lower()
                
                if ext:
                    analysis['languages'][ext] = analysis['languages'].get(ext, 0) + 1
                
                # Check for important files
                filename = os.path.basename(path)
                if filename.lower() in ['requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'setup.py']:
                    analysis['has_requirements'] = True
                    analysis['config_files'].append(filename)
                elif filename.lower() in ['package.json', 'package-lock.json', 'yarn.lock']:
                    analysis['has_package_json'] = True
                    analysis['config_files'].append(filename)
                elif filename.lower() in ['dockerfile', 'docker-compose.yml', 'docker-compose.yaml']:
                    analysis['has_dockerfile'] = True
                    analysis['config_files'].append(filename)
                elif 'test' in filename.lower() or filename.startswith('test_'):
                    analysis['has_tests'] = True
                
                if len(analysis['files']) < 100:
                    analysis['files'].append(path)
            
            elif item['type'] == 'tree' and len(analysis['directories']) < 50:
                analysis['directories'].append(item['path'])
        
        return analysis, None
    
    except Exception as e:
        return None, f"Error: {str(e)}"

def fetch_github_file_content(owner, repo, file_path, branch='main', github_token=None):
    """Fetch content of a specific file from GitHub"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
        headers = {}
        if github_token:
            headers['Authorization'] = f'token {github_token}'
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = response.json().get('content', '')
            decoded = base64.b64decode(content).decode('utf-8')
            return decoded[:2000]  # Limit content
        return None
    except:
        return None

def analyze_local_directory(path):
    """Analyze local project directory"""
    analysis = {
        'files': [],
        'directories': [],
        'languages': {},
        'file_count': 0,
        'has_requirements': False,
        'has_package_json': False,
        'has_dockerfile': False,
        'has_tests': False,
        'config_files': [],
        'is_local': True
    }
    
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in [
                '.git', 'node_modules', '__pycache__', 'venv', 
                '.venv', 'dist', 'build', '.next', '.idea'
            ]]
            
            rel_root = os.path.relpath(root, path)
            
            for file in files:
                analysis['file_count'] += 1
                file_path = os.path.join(rel_root, file)
                ext = Path(file).suffix.lower()
                
                if ext:
                    analysis['languages'][ext] = analysis['languages'].get(ext, 0) + 1
                
                filename = file.lower()
                if filename in ['requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'setup.py']:
                    analysis['has_requirements'] = True
                    analysis['config_files'].append(file)
                elif filename in ['package.json', 'package-lock.json', 'yarn.lock']:
                    analysis['has_package_json'] = True
                    analysis['config_files'].append(file)
                elif filename in ['dockerfile', 'docker-compose.yml', 'docker-compose.yaml']:
                    analysis['has_dockerfile'] = True
                    analysis['config_files'].append(file)
                elif 'test' in filename or file.startswith('test_'):
                    analysis['has_tests'] = True
                
                if len(analysis['files']) < 100:
                    analysis['files'].append(file_path)
            
            if len(analysis['directories']) < 50:
                analysis['directories'].extend([os.path.join(rel_root, d) for d in dirs])
    
    except Exception as e:
        st.error(f"Error analyzing directory: {e}")
    
    return analysis

def read_local_file(file_path, max_lines=50):
    """Read local file content"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[:max_lines]
            return ''.join(lines)
    except:
        return None

def create_analysis_prompt(analysis, is_github=False):
    """Create prompt for Groq API"""
    
    if is_github:
        prompt = f"""You are an expert software documentation writer. Analyze this GitHub repository:

Repository: {analysis.get('name', 'Unknown')}
Description: {analysis.get('description', 'No description')}
Primary Language: {analysis.get('language', 'Unknown')}
Stars: {analysis.get('stars', 0)} | Forks: {analysis.get('forks', 0)} | Issues: {analysis.get('open_issues', 0)}
Topics: {', '.join(analysis.get('topics', []))}

Project Statistics:
- Total Files: {analysis['file_count']}
- File Types: {json.dumps(analysis['languages'], indent=2)}
- Has Dependencies: {analysis['has_requirements'] or analysis['has_package_json']}
- Has Docker: {analysis['has_dockerfile']}
- Has Tests: {analysis['has_tests']}
- Config Files: {', '.join(analysis['config_files'])}

Repository Structure (sample):
{chr(10).join(analysis['files'][:30])}
"""
    else:
        prompt = f"""You are an expert software documentation writer. Analyze this local project:

Project Statistics:
- Total Files: {analysis['file_count']}
- File Types: {json.dumps(analysis['languages'], indent=2)}
- Has Dependencies: {analysis['has_requirements'] or analysis['has_package_json']}
- Has Docker: {analysis['has_dockerfile']}
- Has Tests: {analysis['has_tests']}
- Config Files: {', '.join(analysis['config_files'])}

Project Structure (sample):
{chr(10).join(analysis['files'][:30])}
"""
    
    prompt += """
Based on this information, provide a detailed analysis including:
1. Project type and purpose
2. Technology stack and frameworks
3. Architecture and structure
4. Key features and capabilities
5. Installation requirements
6. Usage patterns
7. Notable patterns or best practices

Format as a structured, detailed analysis."""
    
    return prompt

def create_readme_prompt(project_name, analysis_result, github_analysis=None, 
                        user_description="", github_username="", 
                        license_type="MIT", custom_sections=""):
    """Create prompt for README generation"""
    
    github_info = ""
    if github_analysis:
        github_info = f"""
GitHub Repository Info:
- Stars: {github_analysis.get('stars', 0)}
- Forks: {github_analysis.get('forks', 0)}
- Issues: {github_analysis.get('open_issues', 0)}
- Topics: {', '.join(github_analysis.get('topics', []))}
- Repository URL: {github_analysis.get('repo_url', '')}
"""
    
    prompt = f"""Generate a professional, comprehensive README.md file for this GitHub repository.

Project Name: {project_name}
License: {license_type}
{"GitHub Username: " + github_username if github_username else ""}

{github_info}

Project Analysis:
{analysis_result}

{"User Description: " + user_description if user_description else ""}
{"Additional Sections: " + custom_sections if custom_sections else ""}

Create a README.md that includes:
1. Project title with badges (shields.io format for stars, forks, license, language)
2. Compelling description with key features
3. Table of Contents
4. Features section (detailed)
5. Demo/Screenshots section (placeholder)
6. Prerequisites
7. Installation (step-by-step with code blocks)
8. Usage (with examples and code snippets)
9. API Documentation (if applicable)
10. Configuration options
11. Project structure
12. Testing instructions
13. Deployment guide (if applicable)
14. Contributing guidelines
15. License
16. Authors/Contributors
17. Acknowledgments
18. Support/Contact

Use emojis, proper markdown formatting, code blocks with syntax highlighting.
Make it visually appealing and comprehensive.
Include actual badge URLs using shields.io.

Return ONLY the README markdown content."""
    
    return prompt

def call_groq_api(api_key, prompt, model="llama-3.3-70b-versatile"):
    """Call Groq API"""
    try:
        client = Groq(api_key=api_key)
        
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert technical writer specializing in software documentation and README files. Create professional, comprehensive, and visually appealing documentation."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            model=model,
            temperature=0.7,
            max_tokens=4096,
        )
        
        return chat_completion.choices[0].message.content
    
    except Exception as e:
        return f"Error calling Groq API: {str(e)}"

# Initialize session state
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'readme_content' not in st.session_state:
    st.session_state.readme_content = None
if 'project_analysis' not in st.session_state:
    st.session_state.project_analysis = None
if 'github_analysis' not in st.session_state:
    st.session_state.github_analysis = None

# Main App
st.title("🤖 AI-Powered README Generator")
st.title("Developed by Tushar kamthe")
st.markdown("*Powered by Groq LLM - Works with GitHub repos & local projects*")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    use_custom_api=st.checkbox("Use Custom API Key ",value=False)
    if use_custom_api:
       
        api_key = st.text_input(
            "Groq API Key *",
            type="password",
        )
        if not api_key:
            st.markdown("[Get Free API Key](https://console.groq.com)")
    else:
        api_key=DEFAULT_GROQ_API_KEY
        st.success("✅ Using default API key")
    
    
    
    st.divider()
    
    github_token = st.text_input(
        "GitHub Token (Optional)",
        type="password",
        help="For private repos or higher rate limits"
    )
    
    st.divider()
    
    model = st.selectbox(
        "AI Model",
        ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768","qwen/qwen3-32b","groq/compound","groq/compound-mini","llama-3.1-8b-instant","meta-llama/llama-4-maverick-17b-128e-instruct","meta-llama/llama-4-scout-17b-16e-instruct","meta-llama/llama-guard-4-12b","moonshotai/kimi-k2-instruct-0905","openai/gpt-oss-20b"]
    )
    
    st.divider()
    
    st.markdown("""
    ### 📖 Supported Sources
    - ✅ GitHub Public Repos
    - ✅ GitHub Private Repos (with token)
    - ✅ Local Directories
    
    ### ✨ Features
    - AI-powered analysis
    - Smart badge generation
    - Professional formatting
    - Customizable sections
    
    ### 💡 Tips
    - Use GitHub token for private repos
    - Add context for better results
    - Regenerate for variations
    """)

# Main tabs
tab1, tab2, tab3, tab4 = st.tabs(["📁 Project Input", "🔍 AI Analysis", "📝 Generate README", "📄 Preview"])

with tab1:
    st.header("Project Information")
    
    source_type = st.radio(
        "Source Type",
        ["🌐 GitHub Repository", "💻 Local Directory", "✍️ Manual Input"],
        horizontal=True
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        project_name = st.text_input("Project Name *", placeholder="my-awesome-project")
        github_username = st.text_input("GitHub Username", placeholder="yourusername")
    
    with col2:
        license_type = st.selectbox(
            "License",
            ["MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause", "ISC", "AGPL-3.0"]
        )
    
    st.divider()
    
    if source_type == "🌐 GitHub Repository":
        st.subheader("GitHub Repository")
        
        github_url = st.text_input(
            "Repository URL",
            placeholder="https://github.com/username/repository"
        )
        
        if github_url:
            if st.button("🔍 Fetch Repository", type="primary", use_container_width=True):
                with st.spinner("Fetching from GitHub..."):
                    analysis, error = fetch_github_repo_structure(github_url, github_token)
                    
                    if error:
                        st.error(f"❌ {error}")
                        if "rate limit" in error.lower():
                            st.info("💡 Tip: Add a GitHub token in the sidebar for higher rate limits")
                    else:
                        st.session_state.project_analysis = analysis
                        st.session_state.github_analysis = analysis
                        
                        col1, col2, col3, col4, col5 = st.columns(5)
                        col1.metric("Files", analysis['file_count'])
                        col2.metric("Languages", len(analysis['languages']))
                        col3.metric("⭐ Stars", analysis['stars'])
                        col4.metric("🔱 Forks", analysis['forks'])
                        col5.metric("📝 Issues", analysis['open_issues'])
                        
                        if analysis.get('topics'):
                            st.info(f"📌 Topics: {', '.join(analysis['topics'])}")
                        
                        st.success("✅ Repository fetched! Go to 'AI Analysis' tab")
    
    elif source_type == "💻 Local Directory":
        st.subheader("Local Directory")
        
        local_path = st.text_input(
            "Directory Path",
            placeholder="/path/to/your/project"
        )
        
        if local_path:
            if os.path.exists(local_path):
                st.success(f"✅ Directory found: {local_path}")
                
                if st.button("🔍 Scan Directory", type="primary", use_container_width=True):
                    with st.spinner("Scanning..."):
                        analysis = analyze_local_directory(local_path)
                        st.session_state.project_analysis = analysis
                        st.session_state.local_path = local_path
                        
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Files", analysis['file_count'])
                        col2.metric("Languages", len(analysis['languages']))
                        col3.metric("Tests", "✅" if analysis['has_tests'] else "❌")
                        col4.metric("Docker", "✅" if analysis['has_dockerfile'] else "❌")
                        
                        st.success("✅ Directory scanned! Go to 'AI Analysis' tab")
            else:
                st.error("❌ Directory not found")
    
    else:  # Manual Input
        st.subheader("Manual Input")
        
        description = st.text_area(
            "Project Description",
            placeholder="Describe your project...",
            height=120
        )
        
        tech_stack = st.text_input(
            "Technologies",
            placeholder="Python, React, Docker, PostgreSQL"
        )
        
        features = st.text_area(
            "Key Features",
            placeholder="Feature 1\nFeature 2\nFeature 3",
            height=100
        )
        
        st.session_state.manual_input = {
            'description': description,
            'tech_stack': tech_stack,
            'features': features
        }

with tab2:
    st.header("🔍 AI-Powered Analysis")
    
    if not api_key:
        st.warning("⚠️ Enter Groq API key in sidebar")
    elif st.session_state.project_analysis or st.session_state.get('manual_input'):
        
        context = st.text_area(
            "Additional Context (Optional)",
            placeholder="Any specific details for the AI...",
            height=100
        )
        
        if st.button("🚀 Analyze with AI", type="primary", use_container_width=True):
            with st.spinner("🤖 AI analyzing..."):
                
                if st.session_state.project_analysis:
                    is_github = 'repo_url' in st.session_state.project_analysis
                    prompt = create_analysis_prompt(
                        st.session_state.project_analysis,
                        is_github
                    )
                    if context:
                        prompt += f"\n\nAdditional Context: {context}"
                else:
                    manual = st.session_state.manual_input
                    prompt = f"""Analyze this project:

Description: {manual['description']}
Technologies: {manual['tech_stack']}
Features: {manual['features']}
{f"Context: {context}" if context else ""}

Provide comprehensive analysis with insights."""
                
                result = call_groq_api(api_key, prompt, model)
                st.session_state.analysis_result = result
        
        if st.session_state.analysis_result:
            st.success("✅ Analysis complete!")
            st.markdown("### 📊 AI Analysis")
            st.markdown(st.session_state.analysis_result)
            st.info("👉 Go to 'Generate README' tab")
    else:
        st.info("👈 Provide project input first")

with tab3:
    st.header("📝 Generate README")
    
    if not api_key:
        st.warning("⚠️ Enter API key in sidebar")
    elif not st.session_state.analysis_result:
        st.info("👈 Complete AI analysis first")
    else:
        
        extra_desc = st.text_area(
            "Extra Description",
            placeholder="Additional details...",
            height=80
        )
        
        custom_sections = st.text_input(
            "Custom Sections",
            placeholder="Screenshots, Roadmap, FAQ"
        )
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if st.button("✨ Generate README", type="primary", use_container_width=True):
                with st.spinner("🤖 Generating README..."):
                    prompt = create_readme_prompt(
                        project_name,
                        st.session_state.analysis_result,
                        st.session_state.github_analysis,
                        extra_desc,
                        github_username,
                        license_type,
                        custom_sections
                    )
                    
                    readme = call_groq_api(api_key, prompt, model)
                    st.session_state.readme_content = readme
                    st.success("✅ README generated!")
        
        with col2:
            if st.session_state.readme_content:
                if st.button("🔄 Regenerate", use_container_width=True):
                    st.rerun()

with tab4:
    st.header("📄 Preview & Download")
    
    if st.session_state.readme_content:
        
        st.markdown("### Preview")
        st.markdown(st.session_state.readme_content)
        
        st.divider()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.download_button(
                "⬇️ Download README.md",
                st.session_state.readme_content,
                "README.md",
                "text/markdown",
                use_container_width=True
            )
        
        with col2:
            if st.button("📋 View Raw", use_container_width=True):
                st.code(st.session_state.readme_content, language="markdown")
        
        with col3:
            if st.button("🗑️ Clear All", use_container_width=True):
                for key in ['readme_content', 'analysis_result', 'project_analysis', 'github_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
        
    else:
        st.info("👈 Generate README first")

st.markdown("---")
st.markdown(
    "<div style='text-align: center'><p>Made with ❤️ using Streamlit & Groq | "
    "<a href='https://console.groq.com'>Get API Key</a></p></div>",
    unsafe_allow_html=True
)
