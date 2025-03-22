python postmand2openapi.py  --config config.yaml --search-dir . 


python openapi2confluence.py \
    --confluence-base-url "https://runwhen.atlassian.net/wiki" \
    --username "shea.stewart@runwhen.com" \
    --api-token "$API_TOKEN" \
    --space-key "api" \
    --parent-page-id 22642880  \
    --master-file "papi.postman_collection.yaml" \
    --master-page-title "My API - Full" \
    --partials-page-title "My API - Partial Docs" \
    --output-dir ./partials



