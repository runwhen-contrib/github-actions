#!/usr/bin/env python3

import os
import ast
import inspect
from pathlib import Path
from atlassian import Confluence
import markdown
from bs4 import BeautifulSoup
import logging
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentationGenerator:
    def __init__(self):
        self.doc_type = os.getenv('DOC_TYPE', 'markdown').lower()
        self.libraries_path = os.getenv('LIBRARIES_PATH', 'libraries')
        
        # Initialize Confluence client only if needed
        if self.doc_type in ['confluence', 'both']:
            self._init_confluence()
        else:
            self.confluence = None

    def _init_confluence(self):
        """Initialize Confluence client if needed."""
        required_env_vars = [
            'CONFLUENCE_URL',
            'CONFLUENCE_USERNAME',
            'CONFLUENCE_API_TOKEN',
            'CONFLUENCE_SPACE_KEY',
            'CONFLUENCE_PARENT_PAGE_ID'
        ]
        
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables for Confluence: {', '.join(missing_vars)}")
            
        self.confluence = Confluence(
            url=os.getenv('CONFLUENCE_URL'),
            username=os.getenv('CONFLUENCE_USERNAME'),
            password=os.getenv('CONFLUENCE_API_TOKEN'),
            cloud=True
        )
        self.space_key = os.getenv('CONFLUENCE_SPACE_KEY')
        self.parent_page_id = os.getenv('CONFLUENCE_PARENT_PAGE_ID')

    def parse_library_files(self):
        """Parse all Python library files and extract keyword documentation."""
        libraries = {}
        lib_path = Path(self.libraries_path)
        
        if not lib_path.exists():
            raise FileNotFoundError(f"Libraries directory not found at {self.libraries_path}")

        for file_path in lib_path.rglob('*.py'):
            # Skip __init__.py and other special files
            if file_path.name.startswith('__'):
                continue
                
            library_name = file_path.stem
            try:
                keywords = self._extract_keywords_from_python(file_path)
                if keywords:  # Only add if we found keywords
                    libraries[library_name] = keywords
            except Exception as e:
                logger.warning(f"Error parsing {file_path}: {e}")
                continue
            
        return libraries

    def _extract_keywords_from_python(self, file_path):
        """Extract keywords and their documentation from a Python file."""
        keywords = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the Python file
            tree = ast.parse(content)
            
            # Extract keywords from classes and functions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Skip private methods
                    if node.name.startswith('_'):
                        continue
                    
                    keyword = self._parse_function_as_keyword(node, content)
                    if keyword:
                        keywords.append(keyword)
                
                elif isinstance(node, ast.ClassDef):
                    # Extract methods from classes
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                            keyword = self._parse_function_as_keyword(item, content, class_name=node.name)
                            if keyword:
                                keywords.append(keyword)
        
        except Exception as e:
            logger.error(f"Error parsing Python file {file_path}: {e}")
            return []
            
        return keywords

    def _parse_function_as_keyword(self, func_node, content, class_name=None):
        """Parse a function node as a Robot Framework keyword."""
        keyword_name = func_node.name
        if class_name:
            keyword_name = f"{class_name}.{keyword_name}"
        
        # Extract docstring
        docstring = ast.get_docstring(func_node) or ""
        
        # Extract arguments
        arguments = []
        for arg in func_node.args.args:
            if arg.arg != 'self':  # Skip self parameter
                arguments.append(arg.arg)
        
        # Extract return information from docstring
        returns = []
        examples = []
        
        if docstring:
            # Look for return information in docstring
            return_match = re.search(r'(?:Returns?|Return value):\s*(.+)', docstring, re.IGNORECASE)
            if return_match:
                returns.append(return_match.group(1).strip())
            
            # Look for examples in docstring
            example_matches = re.findall(r'(?:Example|Examples?):\s*\n(.+?)(?:\n\n|\n[A-Z]|\Z)', docstring, re.DOTALL | re.IGNORECASE)
            for match in example_matches:
                examples.extend([line.strip() for line in match.split('\n') if line.strip()])
        
        # Clean up docstring - remove Returns and Examples sections for main documentation
        clean_doc = re.sub(r'(?:Returns?|Return value):\s*.+', '', docstring, flags=re.IGNORECASE)
        clean_doc = re.sub(r'(?:Example|Examples?):\s*\n.+', '', clean_doc, flags=re.DOTALL | re.IGNORECASE)
        clean_doc = clean_doc.strip()
        
        return {
            'name': keyword_name,
            'documentation': clean_doc,
            'arguments': arguments,
            'returns': returns,
            'examples': examples
        }

    def _categorize_keywords(self, libraries):
        """Categorize keywords by functionality for better organization."""
        categories = {
            'Core Operations': [],
            'Kubernetes': [],
            'File Operations': [],
            'HTTP/API': [],
            'Cloud Services': [],
            'Monitoring & Metrics': [],
            'Utilities': [],
            'Other': []
        }
        
        for lib_name, keywords in libraries.items():
            for keyword in keywords:
                name = keyword['name'].lower()
                doc = keyword['documentation'].lower()
                
                # Categorize based on keyword name and documentation
                if any(term in name or term in doc for term in ['k8s', 'kubernetes', 'kubectl', 'pod', 'deployment', 'service']):
                    categories['Kubernetes'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['http', 'api', 'request', 'curl', 'rest', 'endpoint']):
                    categories['HTTP/API'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['file', 'path', 'directory', 'folder', 'read', 'write']):
                    categories['File Operations'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['aws', 'gcp', 'azure', 'cloud', 's3', 'ec2']):
                    categories['Cloud Services'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['metric', 'monitor', 'alert', 'prometheus', 'grafana']):
                    categories['Monitoring & Metrics'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['rw.core', 'core', 'issue', 'report', 'runbook']):
                    categories['Core Operations'].append((lib_name, keyword))
                elif any(term in name or term in doc for term in ['parse', 'format', 'convert', 'utility', 'helper']):
                    categories['Utilities'].append((lib_name, keyword))
                else:
                    categories['Other'].append((lib_name, keyword))
        
        # Remove empty categories
        return {cat: keywords for cat, keywords in categories.items() if keywords}

    def _generate_robot_example(self, keyword):
        """Generate Robot Framework syntax example for a keyword."""
        keyword_name = keyword['name']
        args = keyword['arguments']
        
        # Create a realistic Robot Framework example
        example = f"${{{keyword_name.lower().replace('.', '_')}_result}}=    {keyword_name}"
        
        if args:
            # Add example arguments
            example_args = []
            for arg in args[:3]:  # Limit to first 3 args for readability
                if 'path' in arg.lower() or 'file' in arg.lower():
                    example_args.append("/path/to/file")
                elif 'url' in arg.lower():
                    example_args.append("https://example.com")
                elif 'name' in arg.lower():
                    example_args.append("example-name")
                elif 'namespace' in arg.lower():
                    example_args.append("default")
                else:
                    example_args.append(f"${{{arg}}}")
            
            if len(args) > 3:
                example_args.append("...")
            
            example += "    " + "    ".join(example_args)
        
        return example

    def generate_markdown(self, libraries):
        """Generate markdown documentation from parsed libraries."""
        md_content = "# RunWhen CodeCollection Libraries Documentation\n\n"
        
        # Overview section
        md_content += "## Overview\n\n"
        md_content += "This documentation covers the Python libraries that provide Robot Framework keywords for the RunWhen CodeCollection. "
        md_content += "These keywords are designed to help you create effective runbooks and SLIs for troubleshooting and monitoring.\n\n"
        
        # Quick stats
        total_keywords = sum(len(keywords) for keywords in libraries.values())
        md_content += f"**Total Libraries:** {len(libraries)}  \n"
        md_content += f"**Total Keywords:** {total_keywords}\n\n"
        
        # Getting started section
        md_content += "## Getting Started\n\n"
        md_content += "To use these keywords in your Robot Framework files:\n\n"
        md_content += "1. Import the library in your Robot Framework file\n"
        md_content += "2. Use the keywords in your test cases or tasks\n"
        md_content += "3. Refer to the examples below for syntax\n\n"
        md_content += "### Example Robot Framework Usage\n\n"
        md_content += "```robotframework\n"
        md_content += "*** Settings ***\n"
        md_content += "Library    RW.Core\n"
        md_content += "Library    RW.K8s\n\n"
        md_content += "*** Tasks ***\n"
        md_content += "Check Pod Status\n"
        md_content += "    ${pods}=    RW.K8s.Get Pods    namespace=default\n"
        md_content += "    RW.Core.Add Pre To Report    Found ${pods} pods\n"
        md_content += "```\n\n"
        
        # Categorize keywords
        categories = self._categorize_keywords(libraries)
        
        # Table of contents
        md_content += "## Table of Contents\n\n"
        for category in categories.keys():
            md_content += f"- [{category}](#{category.lower().replace(' ', '-').replace('/', '').replace('&', '')})\n"
        md_content += "\n"
        
        # Generate content by category
        for category, category_keywords in categories.items():
            md_content += f"## {category}\n\n"
            
            if category_keywords:
                # Group by library within category
                libs_in_category = {}
                for lib_name, keyword in category_keywords:
                    if lib_name not in libs_in_category:
                        libs_in_category[lib_name] = []
                    libs_in_category[lib_name].append(keyword)
                
                for lib_name, keywords in libs_in_category.items():
                    md_content += f"### {lib_name} Library\n\n"
                    
                    for keyword in keywords:
                        md_content += f"#### {keyword['name']}\n\n"
                        
                        # Add documentation
                        if keyword['documentation']:
                            md_content += f"{keyword['documentation']}\n\n"
                        
                        # Add arguments
                        if keyword['arguments']:
                            md_content += "**Arguments:**\n\n"
                            for arg in keyword['arguments']:
                                md_content += f"- `{arg}`\n"
                            md_content += "\n"
                        
                        # Add return values
                        if keyword['returns']:
                            md_content += "**Returns:**\n\n"
                            for ret in keyword['returns']:
                                md_content += f"- {ret}\n"
                            md_content += "\n"
                        
                        # Add Robot Framework example
                        md_content += "**Robot Framework Example:**\n\n"
                        md_content += "```robotframework\n"
                        md_content += self._generate_robot_example(keyword)
                        md_content += "\n```\n\n"
                        
                        # Add original examples if available
                        if keyword['examples']:
                            md_content += "**Additional Examples:**\n\n"
                            md_content += "```python\n"
                            for example in keyword['examples']:
                                md_content += f"{example}\n"
                            md_content += "```\n\n"
                        
                        md_content += "---\n\n"
        
        # Quick reference section
        md_content += "## Quick Reference\n\n"
        md_content += "### All Keywords by Library\n\n"
        for lib_name, keywords in libraries.items():
            md_content += f"**{lib_name}:**\n"
            for keyword in keywords:
                md_content += f"- `{keyword['name']}`\n"
            md_content += "\n"
                
        return md_content

    def update_confluence(self, markdown_content):
        """Update Confluence with the generated documentation."""
        if not self.confluence:
            logger.warning("Confluence client not initialized. Skipping Confluence update.")
            return
            
        # Convert markdown to HTML
        html_content = markdown.markdown(markdown_content)
        
        # Add Confluence-specific formatting
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Add navigation panel
        nav_panel = soup.new_tag('div', attrs={'class': 'panel'})
        nav_panel['style'] = 'float: right; margin: 0 0 1em 1em;'
        
        # Create table of contents
        toc = soup.new_tag('div', attrs={'class': 'toc'})
        toc_header = soup.new_tag('h3')
        toc_header.string = 'Table of Contents'
        toc.append(toc_header)
        
        # Add navigation links
        for h2 in soup.find_all('h2'):
            if h2.string:
                link = soup.new_tag('p')
                link.string = f"• {h2.string}"
                toc.append(link)
        
        nav_panel.append(toc)
        if soup.body:
            soup.body.insert(0, nav_panel)
        
        # Create or update the documentation page
        page_title = "RunWhen CodeCollection Libraries Documentation"
        
        try:
            # Check if page exists
            existing_page = self.confluence.get_page_by_title(
                space=self.space_key,
                title=page_title
            )
            
            if existing_page:
                # Update existing page
                self.confluence.update_page(
                    page_id=existing_page['id'],
                    title=page_title,
                    body=str(soup),
                    parent_id=self.parent_page_id,
                    type='page'
                )
                logger.info(f"Updated existing Confluence page: {page_title}")
            else:
                # Create new page
                self.confluence.create_page(
                    space=self.space_key,
                    title=page_title,
                    body=str(soup),
                    parent_id=self.parent_page_id,
                    type='page'
                )
                logger.info(f"Created new Confluence page: {page_title}")
        except Exception as e:
            logger.error(f"Error updating Confluence: {e}")

    def save_markdown(self, markdown_content):
        """Save markdown documentation to a file."""
        output_path = Path('docs')
        output_path.mkdir(exist_ok=True)
        
        with open(output_path / 'libraries_documentation.md', 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        logger.info("Saved markdown documentation to docs/libraries_documentation.md")

def main():
    try:
        generator = DocumentationGenerator()
        
        # Parse libraries
        logger.info("Parsing Python library files...")
        libraries = generator.parse_library_files()
        
        if not libraries:
            logger.warning("No libraries found or parsed successfully!")
            return
        
        logger.info(f"Found {len(libraries)} libraries with keywords")
        
        # Generate markdown
        logger.info("Generating markdown documentation...")
        markdown_content = generator.generate_markdown(libraries)
        
        # Save markdown if needed
        if generator.doc_type in ['markdown', 'both']:
            generator.save_markdown(markdown_content)
        
        # Update Confluence if needed
        if generator.doc_type in ['confluence', 'both']:
            logger.info("Updating Confluence documentation...")
            generator.update_confluence(markdown_content)
        
        logger.info("Documentation generation completed successfully!")
        
    except Exception as e:
        logger.error(f"Error generating documentation: {str(e)}")
        raise

if __name__ == "__main__":
    main() 