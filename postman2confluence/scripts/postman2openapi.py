import os
import json
import yaml
import argparse
import requests  # Not strictly needed unless uploading to Confluence, shown previously

def parse_items_recursive(items, paths_dict):
    """
    Recursively handle folders vs. actual request items.
    """
    for item in items:
        if "item" in item:
            # It's a folder with sub-items
            parse_items_recursive(item["item"], paths_dict)
        else:
            # It's presumably a single request
            parse_single_request(item, paths_dict)

def parse_single_request(item, paths_dict):
    """
    Convert a single Postman request into an OpenAPI path + operation.
    """
    request = item.get("request", {})
    if not request:
        return

    method = request.get("method", "GET").lower()
    url_data = request.get("url", {})
    if isinstance(url_data, str):
        url_data = {"raw": url_data}

    # Get the path array from Postman, filter out any empty segments
    raw_segments = url_data.get("path", [])
    filtered_segments = [seg for seg in raw_segments if seg]  # skip empty strings

    # Convert placeholders like ":foo" -> "{foo}"
    converted_segments = []
    for seg in filtered_segments:
        if seg.startswith(":"):
            seg = "{" + seg[1:] + "}"
        converted_segments.append(seg)

    # Build the final path string
    if converted_segments:
        openapi_path = "/" + "/".join(converted_segments)
    else:
        # fallback if we have raw only
        raw_url = url_data.get("raw", "")
        openapi_path = parse_path_from_raw(raw_url)

    # Build query params
    query_params = url_data.get("query", [])
    parameters = []
    for q in query_params:
        key = q.get("key")
        if not key:
            continue
        param_desc = q.get("description", "")
        parameters.append({
            "name": key,
            "in": "query",
            "description": param_desc or f"Query param: {key}",
            "required": False,
            "schema": {"type": "string"}
        })

    # Add path (ensure key exists)
    if openapi_path not in paths_dict:
        paths_dict[openapi_path] = {}

    summary = item.get("name", "Untitled Request")
    operation_obj = {
        "summary": summary,
        "responses": {
            "200": {
                "description": "Success"
            }
        }
    }
    if parameters:
        operation_obj["parameters"] = parameters

    # Insert the operation for this method
    paths_dict[openapi_path][method] = operation_obj


def parse_path_from_raw(raw_url):
    """
    Very naive fallback if there's no "url.path" array in Postman.
    """
    result = raw_url
    if "://" in result:
        parts = result.split("://", 1)[1]  # remove scheme
        slash_idx = parts.find("/")
        if slash_idx == -1:
            return "/"
        result = parts[slash_idx:]  # everything after domain

    # remove query
    if "?" in result:
        result = result.split("?", 1)[0]

    # ensure leading slash
    if not result.startswith("/"):
        result = "/" + result

    # also convert placeholders :foo -> {foo}
    segments = []
    for seg in result.strip("/").split("/"):
        if seg.startswith(":"):
            seg = "{" + seg[1:] + "}"
        segments.append(seg)
    path_str = "/" + "/".join(segments) if segments else "/"
    return path_str

def remove_excluded_paths(paths_dict, exclude_list):
    """
    Remove any paths from `paths_dict` if they match an exclusion.

    For each path in exclude_list:
      - If it’s a “parent” like /api/v1, remove /api/v1 itself AND
        any child path that starts with /api/v1/.
      - If it’s a “child” like /api/v1/alerts, remove that exact path only (not sub-paths).
    """

    def should_exclude(path, excludes):
        for ex in excludes:
            ex = ex.strip()
            # exact match => remove
            if path == ex:
                return True
            # if ex is a parent => remove any path starting with ex + "/"
            if path.startswith(ex + "/"):
                return True
        return False

    new_paths = {}
    for path_key, ops in paths_dict.items():
        if should_exclude(path_key, exclude_list):
            continue
        new_paths[path_key] = ops

    # Clear and update
    paths_dict.clear()
    paths_dict.update(new_paths)

def convert_postman_to_openapi(postman_json_path, openapi_output_path, exclude_config_path=None):
    """
    Recursively parse the Postman collection into a minimal OpenAPI 3.0 spec.
    Then remove any excluded paths (parents or children) listed in exclude_config_path (YAML).
    Finally, write the spec to openapi_output_path (JSON or YAML).
    """

    # 1) Load the Postman JSON
    with open(postman_json_path, "r", encoding="utf-8") as f:
        postman_data = json.load(f)

    info = postman_data.get("info", {})
    collection_name = info.get("name", "Unnamed Postman Collection")
    version = info.get("version", {}).get("tag", "1.0.0")  # or just "1.0.0"

    # 2) Minimal OpenAPI skeleton
    openapi_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": collection_name,
            "version": version
        },
        "paths": {}
    }

    # 3) Recursively parse the Postman items
    items = postman_data.get("item", [])
    parse_items_recursive(items, openapi_spec["paths"])

    # 4) If we have an exclude config, load it and remove specified paths
    excluded_list = []
    if exclude_config_path and os.path.exists(exclude_config_path):
        with open(exclude_config_path, "r", encoding="utf-8") as yml_file:
            config = yaml.safe_load(yml_file) or {}
        excluded_list = config.get("excluded_paths", [])

    if excluded_list:
        remove_excluded_paths(openapi_spec["paths"], excluded_list)

    # 5) Write out the final OpenAPI file (JSON or YAML)
    _, ext = os.path.splitext(openapi_output_path.lower())
    with open(openapi_output_path, "w", encoding="utf-8") as out:
        if ext in (".yaml", ".yml"):
            yaml.safe_dump(openapi_spec, out, sort_keys=False)
        else:
            json.dump(openapi_spec, out, indent=2)

    return openapi_output_path

def main():
    parser = argparse.ArgumentParser(description="Convert specified Postman files to OpenAPI, excluding paths from config.")
    parser.add_argument("--config", required=True, help="YAML config with `excluded_paths` and `sources` keys.")
    parser.add_argument("--search-dir", required=True, help="Directory to recursively search for the source JSON files.")
    args = parser.parse_args()

    # 1) Load the config
    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    excluded_paths = config.get("excluded_paths", [])
    sources = config.get("sources", [])

    # 2) Recursively walk `search-dir` looking for files that match `sources`
    matched_files = []
    for root, dirs, files in os.walk(args.search_dir):
        for filename in files:
            if filename in sources:
                full_path = os.path.join(root, filename)
                matched_files.append(full_path)

    if not matched_files:
        print("No matching source files found in directory.")
        return

    print(f"Found these files matching config sources:\n  " + "\n  ".join(matched_files))

    # 3) For each matched file, convert Postman -> OpenAPI
    #    We'll write the output as the same base name with a .yaml extension in the same folder
    for fpath in matched_files:
        base_name = os.path.splitext(os.path.basename(fpath))[0]  
        out_file = "openapi/" + base_name + ".yaml"  
        convert_postman_to_openapi(
            postman_json_path=fpath,
            openapi_output_path=out_file,
            exclude_config_path=args.config
        )
        print(f"Converted {fpath} -> {out_file}")

    print("All done!")

if __name__ == "__main__":
    main()
