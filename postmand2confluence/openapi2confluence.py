#!/usr/bin/env python

import os
import sys
import yaml
import copy
import argparse
import requests
from requests.auth import HTTPBasicAuth
import json

# ------------------------------------------------------
# 1) SPLITTING LOGIC (by path segment after /api/v3)
# ------------------------------------------------------

def split_openapi_by_path_segment(master_path, output_dir):
    """
    Loads the OpenAPI doc at 'master_path', finds paths that begin with /api/v3,
    extracts the first segment after /api/v3 (e.g. /api/v3/workspaces => "workspaces"),
    and groups them into partial docs in 'output_dir/groupname.openapi.yaml'.
    
    Returns a dict of { groupName: partialFilePath }.
    """

    # 1) Load the master OpenAPI
    with open(master_path, "r", encoding="utf-8") as f:
        if master_path.lower().endswith(".json"):
            master_doc = json.load(f)
        else:
            master_doc = yaml.safe_load(f)

    # 2) A base template for each partial
    base_template = {
        "openapi": master_doc.get("openapi", "3.0.0"),
        "info": copy.deepcopy(master_doc.get("info", {})),
        "paths": {}
        # If you have "components" that are needed, you might copy them entirely:
        # "components": copy.deepcopy(master_doc.get("components", {})),
    }

    partial_docs = {}

    all_paths = master_doc.get("paths", {})
    for path_key, path_item in all_paths.items():
        # We only group if path starts with /api/v3
        if not path_key.startswith("/api/v3"):
            continue
        
        # Remove /api/v3 from the front
        remainder = path_key[len("/api/v3"):]  # e.g. "/workspaces/{wid}/..."
        remainder = remainder.lstrip("/")       # e.g. "workspaces/{wid}/..."

        if not remainder:
            # path is exactly /api/v3 with nothing after, skip or call it "root"
            continue

        # first segment is everything up to the next slash
        first_segment = remainder.split("/")[0]  # e.g. "workspaces", "users", "codecollections", etc.

        group_name = first_segment  # You could rename or map it if needed

        # For each method (GET/POST/...), copy the operation
        for method, operation_obj in path_item.items():
            if method not in ["get","put","post","delete","options","head","patch","trace"]:
                continue

            # ensure partial doc for this group
            if group_name not in partial_docs:
                partial_docs[group_name] = copy.deepcopy(base_template)

            paths_dict = partial_docs[group_name]["paths"]
            if path_key not in paths_dict:
                paths_dict[path_key] = {}
            paths_dict[path_key][method] = copy.deepcopy(operation_obj)

    # 3) Write out partial docs
    os.makedirs(output_dir, exist_ok=True)
    result_files = {}
    for group, doc in partial_docs.items():
        out_path = os.path.join(output_dir, f"{group}.openapi.yaml")
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, sort_keys=False)
        result_files[group] = out_path

    return result_files

# ------------------------------------------------------
# 2) CONFLUENCE UTILS
# ------------------------------------------------------

def build_openapi_macro_for_attachment(attachment_name):
    """
    Example macro snippet for embedding an OpenAPI doc from an attachment.
    Adjust if your plugin differs (macro name, parameter name, etc.).
    """
    return f"""
    <ac:structured-macro ac:name="openapi">
      <ac:parameter ac:name="url">attachment://{attachment_name}</ac:parameter>
    </ac:structured-macro>
    """

def upload_attachment(page_id, file_path, confluence_base_url, auth, mime_type="text/yaml"):
    url = f"{confluence_base_url}/rest/api/content/{page_id}/child/attachment"
    headers = {"X-Atlassian-Token": "nocheck"}
    filename = os.path.basename(file_path)

    with open(file_path, "rb") as f:
        files = {'file': (filename, f, mime_type)}
        resp = requests.post(url, files=files, auth=auth, headers=headers)
    resp.raise_for_status()
    return filename

def create_page(title, space_key, parent_id, content, confluence_base_url, auth):
    api_url = f"{confluence_base_url}/rest/api/content"
    headers = {"Accept": "application/json","Content-Type":"application/json"}
    data = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": content,
                "representation": "storage"
            }
        }
    }
    if parent_id:
        data["ancestors"] = [{"id": parent_id}]

    resp = requests.post(api_url, json=data, auth=auth, headers=headers)
    resp.raise_for_status()
    return resp.json()["id"]

def update_page(page_id, title, space_key, new_content, confluence_base_url, auth):
    get_url = f"{confluence_base_url}/rest/api/content/{page_id}"
    get_resp = requests.get(get_url, auth=auth)
    get_resp.raise_for_status()
    page_data = get_resp.json()
    current_version = page_data["version"]["number"]

    put_url = get_url
    headers = {"Accept":"application/json","Content-Type":"application/json"}
    data = {
        "id": page_id,
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "version": {"number": current_version+1},
        "body": {
            "storage": {
                "value": new_content,
                "representation":"storage"
            }
        }
    }
    put_resp = requests.put(put_url, json=data, auth=auth, headers=headers)
    put_resp.raise_for_status()
    return put_resp.json()["id"]

def find_page_by_title_space(title, space_key, confluence_base_url, auth):
    cql = f'space="{space_key}" AND title="{title}"'
    search_url = f"{confluence_base_url}/rest/api/content/search"
    params = {"cql": cql}
    resp = requests.get(search_url, params=params, auth=auth)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None

def create_or_update_page(title, space_key, parent_id, content, confluence_base_url, auth):
    existing_page_id = find_page_by_title_space(title, space_key, confluence_base_url, auth)
    if existing_page_id:
        return update_page(existing_page_id, title, space_key, content, confluence_base_url, auth)
    else:
        return create_page(title, space_key, parent_id, content, confluence_base_url, auth)

def create_or_update_subpage(parent_page_id, title, space_key, content, confluence_base_url, auth):
    """
    Ensures the page is a direct child of 'parent_page_id', searching with ancestor= in the CQL.
    """
    cql = f'space="{space_key}" AND title="{title}" AND ancestor={parent_page_id}'
    search_url = f"{confluence_base_url}/rest/api/content/search"
    params = {"cql": cql}
    resp = requests.get(search_url, params=params, auth=auth)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if results:
        page_id = results[0]["id"]
        return update_page(page_id, title, space_key, content, confluence_base_url, auth)
    else:
        return create_page(title, space_key, parent_page_id, content, confluence_base_url, auth)

# ------------------------------------------------------
# 3) MAIN SCRIPT
# ------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Split an OpenAPI doc by path segment after /api/v3 and upload to Confluence."
    )
    parser.add_argument("--confluence-base-url", required=True, help="e.g. https://yoursite.atlassian.net/wiki")
    parser.add_argument("--username", required=True, help="Confluence user (email for Cloud).")
    parser.add_argument("--api-token", required=True, help="Confluence API token or password.")
    parser.add_argument("--space-key", required=True, help="Confluence space key, e.g. DOC")
    parser.add_argument("--parent-page-id", default=None, help="Parent page ID for the master page.")
    parser.add_argument("--master-file", required=True, help="Path to the master OpenAPI doc (YAML/JSON).")
    parser.add_argument("--master-page-title", default="My API - Full", help="Title for the full doc page.")
    parser.add_argument("--partials-page-title", default="My API - Partial Docs", help="Title for the sub-page that organizes partials.")
    parser.add_argument("--output-dir", default="partials_out", help="Directory where partial YAML files are saved.")
    args = parser.parse_args()

    auth = HTTPBasicAuth(args.username, args.api_token)

    # 1) Split the master openapi doc by path segment
    partials = split_openapi_by_path_segment(args.master_file, args.output_dir)
    print(f"Created partial OpenAPI files in '{args.output_dir}':")
    for grp, path_file in partials.items():
        print(f"  {grp} => {path_file}")

    # 2) Create/Update a "master" page for the full doc
    master_placeholder = "Attaching the full doc..."
    master_page_id = create_or_update_page(
        title=args.master_page_title,
        space_key=args.space_key,
        parent_id=args.parent_page_id,
        content=master_placeholder,
        confluence_base_url=args.confluence_base_url,
        auth=auth
    )
    print(f"Master page '{args.master_page_title}' => {master_page_id}")

    # 2a) Upload the full doc as an attachment, embed macro
    filename = upload_attachment(
        page_id=master_page_id,
        file_path=args.master_file,
        confluence_base_url=args.confluence_base_url,
        auth=auth,
        mime_type="text/yaml"  # or "application/json" if JSON
    )
    macro_body = build_openapi_macro_for_attachment(filename)
    update_page(
        page_id=master_page_id,
        title=args.master_page_title,
        space_key=args.space_key,
        new_content=macro_body,
        confluence_base_url=args.confluence_base_url,
        auth=auth
    )
    print(f"Updated master page with embedded macro for {filename}")

    # 3) Create a "partials" parent page (child of the master) to hold subpages
    partials_parent_content = "Child pages below each contain a partial doc by path group."
    partials_parent_id = create_or_update_subpage(
        parent_page_id=master_page_id,
        title=args.partials_page_title,
        space_key=args.space_key,
        content=partials_parent_content,
        confluence_base_url=args.confluence_base_url,
        auth=auth
    )
    print(f"Partials parent page '{args.partials_page_title}' => {partials_parent_id}")

    # 4) For each partial doc, create a child page under partials_parent_id
    for group_name, partial_file in partials.items():
        page_title = f"{group_name.capitalize()} Endpoints"
        placeholder = f"Attaching partial doc for '{group_name}'"
        child_page_id = create_or_update_subpage(
            parent_page_id=partials_parent_id,
            title=page_title,
            space_key=args.space_key,
            content=placeholder,
            confluence_base_url=args.confluence_base_url,
            auth=auth
        )
        # Upload partial doc
        partial_attach_name = upload_attachment(
            page_id=child_page_id,
            file_path=partial_file,
            confluence_base_url=args.confluence_base_url,
            auth=auth,
            mime_type="text/yaml"
        )
        partial_macro_body = build_openapi_macro_for_attachment(partial_attach_name)
        update_page(
            page_id=child_page_id,
            title=page_title,
            space_key=args.space_key,
            new_content=partial_macro_body,
            confluence_base_url=args.confluence_base_url,
            auth=auth
        )
        print(f"Created/updated child page '{page_title}' => {child_page_id}")

    print("Done! Master doc + partial docs uploaded to Confluence.")

if __name__ == "__main__":
    main()
