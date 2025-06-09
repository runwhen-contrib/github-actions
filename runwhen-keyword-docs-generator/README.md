# RunWhen Keyword Documentation Generator

This GitHub Action automatically generates SDK-style documentation from RunWhen CodeCollection keyword libraries and updates documentation in the specified format (Markdown and/or Confluence).

## Features

- Automatically parses Robot Framework library files
- Extracts keyword documentation and metadata
- Generates Markdown documentation with proper formatting
- Optional Confluence integration
- Supports nested library directories
- Maintains consistent documentation format
- Handles both new and existing Confluence pages
- Automatic commit of generated documentation

## Usage

Add this action to your workflow:

```yaml
name: Generate Keyword Documentation

on:
  push:
    branches: [ main ]
    paths:
      - 'libraries/**'

jobs:
  generate-docs:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # Required for committing documentation
    steps:
      - uses: actions/checkout@v3
      
      - name: Generate Keyword Documentation
        uses: ./.github/actions/runwhen-keyword-docs-generator
        with:
          # Documentation type (markdown, confluence, or both)
          doc_type: 'markdown'  # Optional, defaults to 'markdown'
          
          # Confluence settings (required only if doc_type is 'confluence' or 'both')
          confluence_url: 'https://your-domain.atlassian.net'
          confluence_username: ${{ secrets.CONFLUENCE_USERNAME }}
          confluence_api_token: ${{ secrets.CONFLUENCE_API_TOKEN }}
          confluence_space_key: 'YOUR_SPACE_KEY'
          confluence_parent_page_id: 'PARENT_PAGE_ID'
          
          # Git commit settings
          commit_changes: 'true'  # Optional, defaults to 'true'
          commit_message: 'docs: update keyword documentation'  # Optional
          
          # Optional settings
          libraries_path: 'libraries'  # Optional, defaults to 'libraries'
```

## Documentation Types

The action supports three documentation types:

1. `markdown` (default): Generates Markdown documentation only
2. `confluence`: Updates Confluence pages only
3. `both`: Generates both Markdown and Confluence documentation

## Required Secrets (for Confluence)

When using Confluence integration (`doc_type: 'confluence'` or `'both'`), you need to set up these secrets:

- `CONFLUENCE_USERNAME`: Your Confluence username
- `CONFLUENCE_API_TOKEN`: Your Confluence API token (generate from Atlassian account settings)

## Git Integration

The action can automatically commit generated documentation back to the repository:

- Enabled by default (`commit_changes: 'true'`)
- Uses GitHub Actions bot for commits
- Only commits if there are actual changes
- Customizable commit message
- Requires `contents: write` permission in workflow

To disable automatic commits:
```yaml
with:
  commit_changes: 'false'
```

## Output

### Markdown Documentation
- Generated in the `docs` directory
- `libraries_documentation.md`: Complete documentation of all keywords
- Organized by library name and keyword
- Includes all documentation and metadata
- Automatically committed to the repository (if enabled)

### Confluence Documentation
- Creates or updates a page in your specified Confluence space
- Maintains consistent formatting
- Includes navigation and search capabilities

## Documentation Format

The generated documentation includes:

- Library name and description
- Keyword names and descriptions
- Arguments and return values
- Examples and usage notes
- Related keywords and references

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 