#!/usr/bin/env python3

import http.server
import socketserver
import os
import sys
import json
import logging
import urllib.parse

# Constants
SHOWCASE_INTERNAL_NAME = "showcase.js"
GRAPH_DATA_REQ = {}

class OurSimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_error(self, code, message=None):
        if code == 404:
            logging.warning(f'404 error: {self.path} may not be downloading everything right')
        super().send_error(code, message)

    def do_GET(self):
        global SHOWCASE_INTERNAL_NAME
        logging.info(f"GET request: {self.path}")
        redirect_msg = None
        orig_request = self.path

        # Handle showcase.js redirection if the name is different
        if self.path.startswith("/js/showcase.js") and not os.path.exists(f".{self.path}"):
             # Try to find the actual showcase file
             if os.path.exists(f"js/{SHOWCASE_INTERNAL_NAME}"):
                redirect_msg = f"using our internal {SHOWCASE_INTERNAL_NAME} file"
                self.path = f"/js/{SHOWCASE_INTERNAL_NAME}"

        if self.path.startswith("/locale/messages/strings_") and not os.path.exists(f".{self.path}"):
            redirect_msg = "original request was for a locale we do not have downloaded"
            self.path = "/locale/strings.json"
            
        # Handle config/showcase API call
        if self.path == "/api/v2/config/showcase":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"application": "showcase", "application_version": "25.11.3"}')
            return
            
        # Handle geoip
        if self.path.startswith("/geoip/"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"city":"Unknown","country_code":"US","country_name":"United States"}')
            return
            
        # Handle missing logo
        if self.path.endswith("logo-white-r.svg"):
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.end_headers()
            # Simple transparent SVG
            self.wfile.write(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>')
            self.wfile.write(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>')
            return

        # Parse path and query for all requests
        raw_path, _, query = self.path.partition('?')

        # Handle graph requests via GET (common for persisted queries)
        if self.path.startswith("/api/mp/models/graph"):
            query_args = urllib.parse.parse_qs(query)
            option_name = query_args.get("operationName", [None])[0]
            
            if option_name:
                # Check if we have a downloaded response for this operation
                downloaded_graph_file = os.path.join(os.getcwd(), "api", "mp", "models", f"graph_{option_name}.json")
                if os.path.exists(downloaded_graph_file):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    with open(downloaded_graph_file, "r", encoding="UTF-8") as f:
                        self.wfile.write(f.read().encode('utf-8'))
                    logging.info(f"Served graph GET request for {option_name} from file")
                    return
                
                # Fallback to template if available
                if option_name in GRAPH_DATA_REQ:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(GRAPH_DATA_REQ[option_name].encode('utf-8'))
                    logging.info(f"Served graph GET request for {option_name} from template")
                    return

            if raw_path.startswith("/api/v1/jsonstore/model/plugins/"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
                return

            # If we can't handle it, return empty data to prevent 404s or "No layers" errors
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data": "empty"}')
            return

        if "crop=" in query and raw_path.endswith(".jpg"):
            query_args = urllib.parse.parse_qs(query)
            crop_addition = query_args.get("crop", None)
            if crop_addition is not None:
                crop_addition = f'crop={crop_addition[0]}'
            else:
                crop_addition = ''

            width_addition = query_args.get("width", None)
            if width_addition is not None:
                width_addition = f'width={width_addition[0]}_'
            else:
                width_addition = ''
            test_path = raw_path + width_addition + crop_addition + ".jpg"
            if os.path.exists(f".{test_path}"):
                self.path = test_path
                redirect_msg = "dollhouse/floorplan texture request that we have downloaded, better than generic texture file"
        
        if redirect_msg is not None or orig_request != self.path:
            logging.info(f'Redirecting {orig_request} => {self.path} as {redirect_msg}')

        super().do_GET()

    def do_POST(self):
        post_msg = None
        try:
            if self.path == "/client_log":
                self.send_response(200)
                self.end_headers()
                content_len = int(self.headers.get('content-length', 0))
                post_body = self.rfile.read(content_len).decode('utf-8')
                try:
                    log_data = json.loads(post_body)
                    logging.info(f"CLIENT LOG [{log_data.get('level')}]: {log_data.get('message')}")
                except:
                    logging.info(f"CLIENT LOG (raw): {post_body}")
                return

            if self.path.startswith("/api/v1/event"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
                return

            if self.path.startswith("/api/mp/models/graph") or self.path.startswith("/api/mp/accounts/graph"):
                self.send_response(200)
                self.end_headers()
                content_len = int(self.headers.get('content-length'))
                post_body = self.rfile.read(content_len).decode('utf-8')
                json_body = json.loads(post_body)
                option_name = json_body.get("operationName")
                logging.info(f"Handling Graph POST: {option_name}")
                
                # Check if we have a downloaded response for this operation
                # The downloaded files are usually in api/mp/models/graph_{operationName}.json
                downloaded_graph_file = os.path.join(os.getcwd(), "api", "mp", "models", f"graph_{option_name}.json")
                if os.path.exists(downloaded_graph_file):
                    with open(downloaded_graph_file, "r", encoding="UTF-8") as f:
                        self.wfile.write(f.read().encode('utf-8'))
                    post_msg = f"Served {downloaded_graph_file} for {option_name}"
                    return

                # Check if we have a cached response for this operation (fallback to templates)
                if option_name in GRAPH_DATA_REQ:
                    self.wfile.write(GRAPH_DATA_REQ[option_name].encode('utf-8'))
                    post_msg = f"Served graph of operationName: {option_name} from template"
                    return
                
                self.wfile.write(bytes('{"data": "empty"}', "utf-8"))
                return
        except Exception as error:
            post_msg = f"Error handling POST {self.path}: {str(error)}"
            logging.error(post_msg)
            pass
        finally:
            if post_msg is not None:
                logging.info(f'POST {self.path} result: {post_msg}')

        self.do_GET()

def openDirReadGraphReqs(path, pageId):
    if not os.path.exists(path):
        logging.warning(f"Graph posts directory not found: {path}")
        return

    for root, dirs, filenames in os.walk(path):
        for file in filenames:
            if file.endswith(".json"):
                with open(os.path.join(root, file), "r", encoding="UTF-8") as f:
                    content = f.read().replace("[MATTERPORT_MODEL_ID]", pageId)
                    key = file.replace(".json", "")
                    # Handle graph_ prefix if present in filename but not in operationName
                    if key.startswith("graph_"):
                        key = key.replace("graph_", "")
                    GRAPH_DATA_REQ[key] = content

def run_server(page_id, port=8080):
    global SHOWCASE_INTERNAL_NAME
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    
    # Path to downloads
    base_dir = os.getcwd()
    download_dir = os.path.join(base_dir, "downloads", page_id)
    
    if not os.path.exists(download_dir):
        # Try checking if we are already in the directory or if it's in current dir
        if os.path.exists(page_id):
            download_dir = os.path.join(base_dir, page_id)
        else:
            print(f"Error: Could not find download directory for {page_id}")
            print(f"Expected: {download_dir}")
            sys.exit(1)
            
    # Load graph requests from repo root before changing directory
    graph_posts_dir = os.path.join(base_dir, "graph_posts")
    openDirReadGraphReqs(graph_posts_dir, page_id)
    
    # Change to download directory
    os.chdir(download_dir)
    print(f"Serving from: {download_dir}")
    
    # Find showcase file
    if os.path.exists("js"):
        showcase_files = [f for f in os.listdir("js") if f.startswith("showcase.") and f.endswith(".js")]
        if showcase_files:
            SHOWCASE_INTERNAL_NAME = showcase_files[0]
            print(f"Using showcase file: {SHOWCASE_INTERNAL_NAME}")

    # Start server
    Handler = OurSimpleHTTPRequestHandler
    
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer(("", port), Handler) as httpd:
        print(f"Serving at http://localhost:{port}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 server.py [page_id] [port]")
        sys.exit(1)
        
    page_id = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    
    run_server(page_id, port)
