#!/usr/bin/env python

import os
import sys
import yaml
import copy
import json
import argparse
import requests
from requests.auth import HTTPBasicAuth
from jinja2 import Environment, FileSystemLoader

###############################################################################
# 1) Jinja environment & template rendering
###############################################################################

def get_jinja_env():
    """
    Returns a Jinja2 Environment that loads templates from the local 'templates' folder.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(script_dir, "templates")
    print("DEBUG: Looking for templates in:", template_dir)
    print("DEBUG: Found these files:", os.listdir(template_dir))
    return Environment(loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True)

def render_entire_file_as_text(template_env, template_file, file_path, attachment_filename=None):
    """
    Macro-based approach: read the entire OpenAPI doc from file_path,
    pass it as 'openapi_text' to the template. If your template references a
    specific attachment link, pass 'attachment_filename' for linking.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        doc_text = f.read()
    template = template_env.get_template(template_file)
    return template.render(
        openapi_text=doc_text,
        openapi_json_filename=attachment_filename  # If the template uses this variable
    )

def parse_openapi_for_custom_confluence(file_path):
    """
    For 'custom_confluence.jinja': parse the OpenAPI doc into
    { doc_title, doc_description, openapi_paths }, so the template can
    loop over endpoints & expansions rather than inline all text.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        if file_path.lower().endswith(".json"):
            doc = json.load(f)
        else:
            doc = yaml.safe_load(f)

    doc_title = doc.get("info", {}).get("title", "Untitled API")
    doc_description = doc.get("info", {}).get("description", "")
    paths_data = doc.get("paths", {})

    openapi_paths = {}
    for path_key, path_obj in paths_data.items():
        methods_dict = {}
        for method, operation in path_obj.items():
            if method not in ["get","put","post","delete","options","head","patch","trace"]:
                continue
            summary = operation.get("summary", f"{method.upper()} {path_key}")
            request_example = f"{method.upper()} {path_key}\nAuthorization: Bearer <token>"
            response_example = "{}"
            methods_dict[method] = {
                "summary": summary,
                "requestExample": request_example,
                "responseExample": response_example
            }

        if methods_dict:
            openapi_paths[path_key] = methods_dict

    return {
        "doc_title": doc_title,
        "doc_description": doc_description,
        "openapi_paths": openapi_paths
    }

def render_custom_confluence(template_env, template_file, doc_data, attachment_filename=None):
    """
    Renders 'custom_confluence.jinja', expecting doc_data = { doc_title, doc_description, openapi_paths, ... }.
    If the template references a variable for the attachment (like openapi_json_filename), pass 'attachment_filename'.
    """
    template = template_env.get_template(template_file)
    if attachment_filename:
        doc_data["openapi_json_filename"] = attachment_filename
    return template.render(**doc_data)

###############################################################################
# 2) Splitting logic (/api/v3 path segment)
###############################################################################

def split_openapi_by_path_segment(master_path, output_dir):
    """
    Splits the OpenAPI doc by /api/v3 path => partial docs.
    Returns { groupName: partialFilePath }.
    """
    with open(master_path, "r", encoding="utf-8") as f:
        if master_path.lower().endswith(".json"):
            master_doc = json.load(f)
        else:
            master_doc = yaml.safe_load(f)

    base_template = {
        "openapi": master_doc.get("openapi", "3.0.0"),
        "info": copy.deepcopy(master_doc.get("info", {})),
        "paths": {}
    }

    partial_docs = {}
    for path_key, path_item in master_doc.get("paths", {}).items():
        if not path_key.startswith("/api/v3"):
            continue

        remainder = path_key[len("/api/v3"):]
        remainder = remainder.lstrip("/")
        if not remainder:
            continue

        first_segment = remainder.split("/")[0]
        group_name = first_segment

        for method, operation_obj in path_item.items():
            if method not in ["get","put","post","delete","options","head","patch","trace"]:
                continue

            if group_name not in partial_docs:
                partial_docs[group_name] = copy.deepcopy(base_template)

            paths_dict = partial_docs[group_name]["paths"]
            if path_key not in paths_dict:
                paths_dict[path_key] = {}
            paths_dict[path_key][method] = copy.deepcopy(operation_obj)

    os.makedirs(output_dir, exist_ok=True)
    result_files = {}
    for group, doc in partial_docs.items():
        out_path = os.path.join(output_dir, f"{group}.openapi.yaml")
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, sort_keys=False)
        result_files[group] = out_path

    return result_files

###############################################################################
# 3) Confluence page create/overwrite & stale page pruning
###############################################################################

def find_page_by_title_ancestor(title, space_key, ancestor_id, confluence_base_url, auth):
    cql = f'space="{space_key}" AND title="{title}" AND ancestor={ancestor_id}'
    params = {"cql": cql}
    search_url = f"{confluence_base_url}/rest/api/content/search"
    resp = requests.get(search_url, params=params, auth=auth)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    return results[0]["id"] if results else None

def find_page_by_title_space(title, space_key, confluence_base_url, auth):
    cql = f'space="{space_key}" AND title="{title}"'
    params = {"cql": cql}
    search_url = f"{confluence_base_url}/rest/api/content/search"
    resp = requests.get(search_url, params=params, auth=auth)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    return results[0]["id"] if results else None

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
    if not resp.ok:
        print("Error uploading page content:", resp.status_code, resp.text)
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

def create_or_overwrite_page(title, space_key, parent_id, content, confluence_base_url, auth):
    if parent_id is not None:
        existing_id = find_page_by_title_ancestor(title, space_key, parent_id, confluence_base_url, auth)
    else:
        existing_id = find_page_by_title_space(title, space_key, confluence_base_url, auth)

    if existing_id:
        return update_page(existing_id, title, space_key, content, confluence_base_url, auth)
    else:
        return create_page(title, space_key, parent_id, content, confluence_base_url, auth)

def list_child_pages(confluence_base_url, auth, parent_id):
    url = f"{confluence_base_url}/rest/api/content/{parent_id}/child/page"
    resp = requests.get(url, auth=auth)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    return [(r["id"], r["title"]) for r in results]

def delete_page(confluence_base_url, auth, page_id):
    del_url = f"{confluence_base_url}/rest/api/content/{page_id}"
    resp = requests.delete(del_url, auth=auth)
    resp.raise_for_status()

def prune_stale_pages(confluence_base_url, auth, parent_id, valid_titles):
    existing_children = list_child_pages(confluence_base_url, auth, parent_id)
    for (child_id, child_title) in existing_children:
        if child_title not in valid_titles:
            print(f"Pruning stale page: '{child_title}' (id={child_id})")
            delete_page(confluence_base_url, auth, child_id)

###############################################################################
# 4) Overwrite-friendly attachments in Confluence Cloud with fallback
###############################################################################

def upload_attachment_with_overwrite(page_id, file_path, confluence_base_url, auth):
    """
    Tries POST with '?replace=true' for version-bump. If that fails with
    'Cannot add a new attachment with same file name', we fallback:
     1) find existing attachment
     2) delete it
     3) POST new
    This discards version history, but avoids errors in locked-down instances.
    """
    filename = os.path.basename(file_path)
    mime_type = guess_mime_type(filename)

    # Attempt the 'replace=true' approach first
    url = f"{confluence_base_url}/rest/api/content/{page_id}/child/attachment?replace=true"
    headers = {"X-Atlassian-Token": "nocheck"}

    with open(file_path, "rb") as f:
        files = {"file": (filename, f, mime_type)}
        resp = requests.post(url, files=files, auth=auth, headers=headers)

    if resp.ok:
        # success
        return filename
    else:
        # check if it's the "Cannot add a new attachment with same file name" error
        if resp.status_code == 400 and "Cannot add a new attachment with same file name" in resp.text:
            print(f"replace=true approach failed. We'll fallback to deleting old attachment '{filename}' then re-uploading.")
            # fallback
            fallback_delete_existing_attachment(page_id, filename, confluence_base_url, auth)
            # now re-POST (no replace param)
            url2 = f"{confluence_base_url}/rest/api/content/{page_id}/child/attachment"
            with open(file_path, "rb") as f2:
                files2 = {"file": (filename, f2, mime_type)}
                resp2 = requests.post(url2, files=files2, auth=auth, headers=headers)
            if not resp2.ok:
                print("Error uploading after fallback delete:", resp2.status_code, resp2.text)
            resp2.raise_for_status()
            return filename
        else:
            # Some other error
            print("Error uploading attachment with overwrite:", resp.status_code, resp.text)
            resp.raise_for_status()
    return filename

def fallback_delete_existing_attachment(page_id, filename, confluence_base_url, auth):
    """
    Find the attachment with 'filename' on page_id, DELETE it. 
    This discards version history but ensures we can re-add the new file.
    """
    att_id = find_attachment_id_by_filename(page_id, filename, confluence_base_url, auth)
    if att_id:
        print(f"Deleting existing attachment: {filename} => ID {att_id}")
        del_url = f"{confluence_base_url}/rest/api/content/{att_id}"
        r = requests.delete(del_url, auth=auth)
        if not r.ok:
            print("Error deleting existing attachment:", r.status_code, r.text)
        r.raise_for_status()

def find_attachment_id_by_filename(page_id, filename, confluence_base_url, auth):
    url = f"{confluence_base_url}/rest/api/content/{page_id}/child/attachment"
    params = {"filename": filename}
    r = requests.get(url, params=params, auth=auth)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    return results[0]["id"] if results else None

def guess_mime_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".json":
        return "application/json"
    elif ext in [".yml", ".yaml"]:
        return "application/x-yaml"
    return "application/octet-stream"

###############################################################################
# 5) The Two-Pass Creation Logic
###############################################################################

def create_or_update_page_with_attachment(page_title,
                                          parent_id,
                                          page_body_placeholder,
                                          file_path,
                                          final_render_func,
                                          final_render_kwargs,
                                          space_key,
                                          confluence_base_url,
                                          auth):
    """
    2-pass approach for a single page + file:

    1) Create/Overwrite the page with 'page_body_placeholder'
       so we have a valid page ID.
    2) Attempt to attach file with '?replace=true'. If that fails, delete old and re-post new.
    3) Re-render final page body referencing the attached file (if your template does so).
    4) Update the page
    """
    # Pass A: create or overwrite with placeholder
    page_id = create_or_overwrite_page(
        title=page_title,
        space_key=space_key,
        parent_id=parent_id,
        content=page_body_placeholder,
        confluence_base_url=confluence_base_url,
        auth=auth
    )

    # Step 2: Overwrite-friendly attach 
    attached_name = upload_attachment_with_overwrite(
        page_id=page_id,
        file_path=file_path,
        confluence_base_url=confluence_base_url,
        auth=auth
    )

    # Step 3: Re-render final content
    final_body = final_render_func(attachment_filename=attached_name, **final_render_kwargs)

    # Step 4: update page
    updated_id = update_page(
        page_id=page_id,
        title=page_title,
        space_key=space_key,
        new_content=final_body,
        confluence_base_url=confluence_base_url,
        auth=auth
    )
    return updated_id

###############################################################################
# 6) Main script
###############################################################################

def main():
    parser = argparse.ArgumentParser(
        description="Two-pass creation with fallback to delete if replace=true fails. "
                    "Splits a master doc, references attachments in final page body, prunes stale pages."
    )
    parser.add_argument("--confluence-base-url", required=True, help="e.g. https://yoursite.atlassian.net/wiki")
    parser.add_argument("--username", required=True, help="Confluence user (email).")
    parser.add_argument("--api-token", required=True, help="Confluence API token.")
    parser.add_argument("--space-key", required=True, help="Confluence space key, e.g. DOC.")
    parser.add_argument("--parent-page-id", default=None, help="Parent page for the 'master' page.")
    parser.add_argument("--master-file", required=True, help="Path to the full OpenAPI doc (YAML or JSON).")
    parser.add_argument("--master-page-title", default="Platform Public API", help="Title for the full doc page.")
    parser.add_argument("--partials-page-title", default="API Endpoints", help="Title for partials parent page.")
    parser.add_argument("--output-dir", default="partials_out", help="Where partial .yaml partials are written.")
    parser.add_argument("--template-file", default="openapi_ohara_inline.jinja",
                        help="Which Jinja template to use (in 'templates/' folder). e.g. ohara_inline_example.jinja or custom_confluence.jinja")

    args = parser.parse_args()
    auth = HTTPBasicAuth(args.username, args.api_token)
    env = get_jinja_env()

    # 1) Split the master doc
    partials = split_openapi_by_path_segment(args.master_file, args.output_dir)
    print(f"Split doc => partials in {args.output_dir}:")
    for group_name, fpath in partials.items():
        print(f"  {group_name} => {fpath}")

    # Decide how to produce final content for MASTER doc
    if args.template_file == "custom_confluence.jinja":
        print("\nDetected 'custom_confluence.jinja': parse doc for expansions.")
        master_doc_data = parse_openapi_for_custom_confluence(args.master_file)
        def final_render_master(attachment_filename=None):
            return render_custom_confluence(
                template_env=env,
                template_file=args.template_file,
                doc_data=master_doc_data,
                attachment_filename=attachment_filename
            )
    else:
        print("\nDetected macro-based or other template => inline entire doc as openapi_text.")
        def final_render_master(attachment_filename=None):
            return render_entire_file_as_text(
                template_env=env,
                template_file=args.template_file,
                file_path=args.master_file,
                attachment_filename=attachment_filename
            )

    # 2) Two-pass creation for MASTER
    print(f"\n=== Processing MASTER page: {args.master_page_title} ===")
    master_placeholder = "<p>Attaching master file...</p>"

    master_id = create_or_update_page_with_attachment(
        page_title=args.master_page_title,
        parent_id=args.parent_page_id,
        page_body_placeholder=master_placeholder,
        file_path=args.master_file,
        final_render_func=final_render_master,
        final_render_kwargs={},
        space_key=args.space_key,
        confluence_base_url=args.confluence_base_url,
        auth=auth
    )
    print(f"Master page => {master_id}")

    # 3) Create partials parent page
    partials_parent_id = create_or_overwrite_page(
        title=args.partials_page_title,
        space_key=args.space_key,
        parent_id=master_id,
        content="<p>Child pages for partial docs</p>",
        confluence_base_url=args.confluence_base_url,
        auth=auth
    )
    print(f"\nPartials parent => {partials_parent_id}")

    # 4) For each partial doc
    partial_titles = []
    for group_name, partial_file in partials.items():
        page_title = f"{group_name.capitalize()} Endpoints"
        partial_titles.append(page_title)

        if args.template_file == "custom_confluence.jinja":
            doc_data = parse_openapi_for_custom_confluence(partial_file)
            def final_render_partial(attachment_filename=None, dd=doc_data):
                return render_custom_confluence(
                    template_env=env,
                    template_file=args.template_file,
                    doc_data=dd,
                    attachment_filename=attachment_filename
                )
        else:
            def final_render_partial(attachment_filename=None):
                return render_entire_file_as_text(
                    template_env=env,
                    template_file=args.template_file,
                    file_path=partial_file,
                    attachment_filename=attachment_filename
                )

        print(f"\n=== Creating partial page: {page_title} ===")
        partial_placeholder = "<p>Attaching partial doc...</p>"
        child_id = create_or_update_page_with_attachment(
            page_title=page_title,
            parent_id=partials_parent_id,
            page_body_placeholder=partial_placeholder,
            file_path=partial_file,
            final_render_func=final_render_partial,
            final_render_kwargs={},
            space_key=args.space_key,
            confluence_base_url=args.confluence_base_url,
            auth=auth
        )
        print(f"Partial page => {child_id}")

    # 5) Prune stale partial pages
    print("\nPruning stale partial pages not in:", partial_titles)
    prune_stale_pages(
        confluence_base_url=args.confluence_base_url,
        auth=auth,
        parent_id=partials_parent_id,
        valid_titles=set(partial_titles)
    )

    print("\nDone! Master doc + partials updated, fallback to delete if 'replace=true' fails. "
          f"Template used: {args.template_file}")

###############################################################################
# 7) Done
###############################################################################

if __name__ == "__main__":
    main()
