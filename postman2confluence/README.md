## Usage
```
on:
  workflow_dispatch:

jobs:
  postman_openapi_confluence:
    runs-on: ubuntu-latest
    steps:
      - name: Use Postman->OpenAPI->Confluence Action
        uses: runwhen-contrib/postman2confluence@v1
        with:
          postman-sources: |
            - "papi.postman_collection.json"
            - "other_collection.json"
          exclude-paths: |
            - "/api/v1"
            - "/api/v2/old"
          confluence-base-url: "https://myorg.atlassian.net/wiki"
          confluence-username: ${{ secrets.CONFLUENCE_USER }}
          confluence-api-token: ${{ secrets.CONFLUENCE_TOKEN }}
          space-key: "DOC"
          parent-page-id: "12345"
          master-page-title: "Platform Public API"
          partials-page-title: "Endpoints"
          template-file: "openapi_ohara_inline.jinja"
```

