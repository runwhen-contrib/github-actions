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



/rest/api/user?username=myusername

curl -D- \
   -X GET \
   -H "Authorization: Bearer $API_TOKEN" \
   -H "Content-Type: application/json" \
   "https://runwhen.atlassian.net/wiki/rest/api/space"


{"statusCode":403,"data":{"authorized":false,"valid":true,"errors":[],"successful":false},"message":"com.atlassian.confluence.api.service.exceptions.PermissionException: Could not create content with type page"}

curl -u shea.stewart@runwhen.com:$API_TOKEN \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{
    "type":"page",
    "title":"Test Page",
    "space": {"key":"API"},
    "body":{"storage":{"value":"Hello world","representation":"storage"}}
  }' \
  "https://runwhen.atlassian.net/wiki/rest/api/content"


curl --request GET \
  --url "https://runwhen.atlassian.net/wiki/rest/api/content/22642880?expand=body.storage" \
  --user "shea.stewart@runwhen.com:$API_TOKEN" \
  --header "Accept: application/json"


curl -u "shea.stewart@runwhen.com:$API_TOKEN" \
     -H "Content-Type: application/json" \
     -X POST \
     -d '{
       "type":"page",
       "title":"API Test Page",
       "space":{"key":"API"},
       "body":{"storage":{"value":"Hi","representation":"storage"}}
     }' \
     "https://runwhen.atlassian.net/wiki/rest/api/content"
