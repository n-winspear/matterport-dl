import json
import re
import os
import glob

def patch_index():
    base_dir = "downloads/AxN4GbV5ko7"
    index_path = os.path.join(base_dir, "index.html")
    models_dir = os.path.join(base_dir, "api/mp/models")
    
    if not os.path.exists(index_path):
        print(f"Error: {index_path} not found")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract the JSON string from MP_PREFETCHED_MODELDATA
    match = re.search(r'window\.MP_PREFETCHED_MODELDATA = parseJSON\("(.+?)"\);', content, re.DOTALL)
    if not match:
        print("Error: Could not find MP_PREFETCHED_MODELDATA in index.html")
        return

    json_str = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from index.html: {e}")
        return

    if "queries" not in data:
        data["queries"] = {}

    # Iterate over all graph_*.json files
    graph_files = glob.glob(os.path.join(models_dir, "graph_*.json"))
    print(f"Found {len(graph_files)} graph files to inject.")

    for file_path in graph_files:
        filename = os.path.basename(file_path)
        # Extract operation name: graph_GetLayers.json -> GetLayers
        op_name = filename.replace("graph_", "").replace(".json", "")
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                op_data = json.load(f)
                data["queries"][op_name] = op_data
                print(f"Injected {op_name}")
            except json.JSONDecodeError:
                print(f"Warning: Failed to decode {filename}, skipping.")

    # Re-serialize to JSON string, escaping quotes as expected by the HTML inline script
    new_json_str = json.dumps(data).replace('\\', '\\\\').replace('"', '\\"')
    
    # Replace in content
    new_content = content.replace(match.group(1), new_json_str)
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"Successfully patched {index_path} with all graph data")

if __name__ == "__main__":
    patch_index()
