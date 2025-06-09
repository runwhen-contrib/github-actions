#!/usr/bin/env python3

import os
import yaml
import json
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
        """Parse all library files and extract keyword documentation."""
        libraries = {}
        lib_path = Path(self.libraries_path)
        
        if not lib_path.exists():
            raise FileNotFoundError(f"Libraries directory not found at {self.libraries_path}")

        for file_path in lib_path.rglob('*.robot'):
            library_name = file_path.stem
            libraries[library_name] = self._extract_keywords(file_path)
            
        return libraries

    def _extract_keywords(self, file_path):
        """Extract keywords and their documentation from a Robot Framework file."""
        keywords = []
        current_keyword = None
        current_doc = []
        current_args = []
        current_returns = []
        current_examples = []
        in_documentation = False
        in_examples = False
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
                
            # Check for section headers
            if line.startswith('***'):
                if current_keyword:
                    keywords.append(self._create_keyword_entry(
                        current_keyword, current_doc, current_args,
                        current_returns, current_examples
                    ))
                current_keyword = None
                current_doc = []
                current_args = []
                current_returns = []
                current_examples = []
                in_documentation = False
                in_examples = False
                continue
                
            # Start of a new keyword
            if not line.startswith(' '):
                if current_keyword:
                    keywords.append(self._create_keyword_entry(
                        current_keyword, current_doc, current_args,
                        current_returns, current_examples
                    ))
                current_keyword = line
                current_doc = []
                current_args = []
                current_returns = []
                current_examples = []
                in_documentation = False
                in_examples = False
                continue
                
            # Documentation section
            if line.startswith('    [Documentation]'):
                in_documentation = True
                in_examples = False
                doc_text = line.replace('[Documentation]', '').strip()
                if doc_text:
                    current_doc.append(doc_text)
                continue
                
            # Arguments section
            if line.startswith('    [Arguments]'):
                in_documentation = False
                in_examples = False
                args_text = line.replace('[Arguments]', '').strip()
                if args_text:
                    current_args.extend([arg.strip() for arg in args_text.split('${') if arg.strip()])
                continue
                
            # Return values section
            if line.startswith('    [Return]'):
                in_documentation = False
                in_examples = False
                returns_text = line.replace('[Return]', '').strip()
                if returns_text:
                    current_returns.append(returns_text)
                continue
                
            # Examples section
            if line.startswith('    # Example:'):
                in_documentation = False
                in_examples = True
                example_text = line.replace('# Example:', '').strip()
                if example_text:
                    current_examples.append(example_text)
                continue
                
            # Continue documentation or examples
            if in_documentation and line.startswith('    '):
                current_doc.append(line.strip())
            elif in_examples and line.startswith('    '):
                current_examples.append(line.strip())
                
        # Add the last keyword if exists
        if current_keyword:
            keywords.append(self._create_keyword_entry(
                current_keyword, current_doc, current_args,
                current_returns, current_examples
            ))
            
        return keywords

    def _create_keyword_entry(self, name, doc, args, returns, examples):
        """Create a structured keyword entry."""
        return {
            'name': name,
            'documentation': '\n'.join(doc).strip(),
            'arguments': args,
            'returns': returns,
            'examples': examples
        }

    def generate_markdown(self, libraries):
        """Generate markdown documentation from parsed libraries."""
        md_content = "# RunWhen CodeCollection Libraries Documentation\n\n"
        
        for lib_name, keywords in libraries.items():
            md_content += f"## {lib_name}\n\n"
            
            # Add library description if available
            if keywords and keywords[0].get('documentation'):
                md_content += f"{keywords[0]['documentation']}\n\n"
            
            for keyword in keywords:
                md_content += f"### {keyword['name']}\n\n"
                
                # Add documentation
                if keyword['documentation']:
                    md_content += f"{keyword['documentation']}\n\n"
                
                # Add arguments
                if keyword['arguments']:
                    md_content += "#### Arguments\n\n"
                    for arg in keyword['arguments']:
                        md_content += f"- `{arg}`\n"
                    md_content += "\n"
                
                # Add return values
                if keyword['returns']:
                    md_content += "#### Returns\n\n"
                    for ret in keyword['returns']:
                        md_content += f"- `{ret}`\n"
                    md_content += "\n"
                
                # Add examples
                if keyword['examples']:
                    md_content += "#### Examples\n\n"
                    md_content += "```robotframework\n"
                    for example in keyword['examples']:
                        md_content += f"{example}\n"
                    md_content += "```\n\n"
                
                md_content += "---\n\n"
                
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
        nav_panel['class'] = 'panel'
        
        # Create table of contents
        toc = soup.new_tag('div', attrs={'class': 'toc'})
        toc.append(soup.new_tag('h2'))
        toc.h2.string = 'Table of Contents'
        
        # Add navigation links
        for h2 in soup.find_all('h2'):
            link = soup.new_tag('a', href=f"#{h2.get('id', '')}")
            link.string = h2.string
            toc.append(link)
            toc.append(soup.new_tag('br'))
        
        nav_panel.append(toc)
        soup.body.insert(0, nav_panel)
        
        # Create or update the documentation page
        page_title = "RunWhen CodeCollection Libraries Documentation"
        
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
        logger.info("Parsing library files...")
        libraries = generator.parse_library_files()
        
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