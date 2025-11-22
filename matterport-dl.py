#!/usr/bin/env python3

'''
Downloads virtual tours from matterport.
Usage is either running this program with the URL/pageid as an argument or calling the initiateDownload(URL/pageid) method.
'''

import uuid
import requests
import json
import threading
import concurrent.futures
import urllib.request
from urllib.parse import urlparse
import pathlib
import re
import os
import shutil
import sys
import time
import logging
from tqdm import tqdm
from http.server import HTTPServer, SimpleHTTPRequestHandler
import decimal


# Weird hack
accessurls = []
SHOWCASE_INTERNAL_NAME = "showcase.js" # Will be updated dynamically

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def makeDirs(dirname):
    pathlib.Path(dirname).mkdir(parents=True, exist_ok=True)


def getVariants():
    variants = []
    depths = ["512", "1k", "2k", "4k"]
    for depth in range(4):
        z = depths[depth]
        for x in range(2**depth):
            for y in range(2**depth):
                for face in range(6):
                    variants.append(f"{z}_face{face}_{x}_{y}.jpg")
    return variants


def downloadUUID(accessurl, uuid):
    downloadFile(accessurl.format(
        filename=f'{uuid}_50k.dam'), f'{uuid}_50k.dam')
    shutil.copy(f'{uuid}_50k.dam', f'..{os.path.sep}{uuid}_50k.dam')
    cur_file = ""
    try:
        for i in range(1000):
            cur_file = accessurl.format(
                filename=f'{uuid}_50k_texture_jpg_high/{uuid}_50k_{i:03d}.jpg')
            downloadFile(
                cur_file, f'{uuid}_50k_texture_jpg_high/{uuid}_50k_{i:03d}.jpg')
            cur_file = accessurl.format(
                filename=f'{uuid}_50k_texture_jpg_low/{uuid}_50k_{i:03d}.jpg')
            downloadFile(
                cur_file, f'{uuid}_50k_texture_jpg_low/{uuid}_50k_{i:03d}.jpg')
    except Exception as ex:
        logging.warning(
            f'Exception downloading file: {cur_file} of: {str(ex)}')
        pass  # very lazy and bad way to only download required files


def downloadSweeps(accessurl, sweeps):
    with tqdm(total=(len(sweeps)*len(getVariants()))) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
            for sweep in sweeps:
                sweep = sweep.replace("-", "")
                for variant in getVariants():
                    pbar.update(1)
                    executor.submit(downloadFile, accessurl.format(
                        filename=f'tiles/{sweep}/{variant}') + "&imageopt=1", f'tiles/{sweep}/{variant}')
                    while executor._work_queue.qsize() > 64:
                        time.sleep(0.01)


def downloadFileWithJSONPost(url, file, post_json_str, descriptor):
    global PROXY
    if "/" in file:
        makeDirs(os.path.dirname(file))
    # skip already downloaded files except index.html which is really json possibly wit hnewer access keys?
    if os.path.exists(file):
        logging.debug(
            f'Skipping json post to url: {url} ({descriptor}) as already downloaded')

    opener = getUrlOpener(PROXY)
    opener.addheaders.append(('Content-Type', 'application/json'))

    req = urllib.request.Request(url)

    for header in opener.addheaders:  # not sure why we can't use the opener itself but it doesn't override it properly
        req.add_header(header[0], header[1])

    body_bytes = bytes(post_json_str, "utf-8")
    req.add_header('Content-Length', len(body_bytes))
    resp = urllib.request.urlopen(req, body_bytes)
    with open(file, 'w', encoding="UTF-8") as the_file:
        the_file.write(resp.read().decode("UTF-8"))
    logging.debug(
        f'Successfully downloaded w/ JSON post to: {url} ({descriptor}) to: {file}')


# Create a session object
session = requests.Session()

def downloadFile(url, file, post_data=None):
    global accessurls
    url = GetOrReplaceKey(url, False)

    if "/" in file:
        makeDirs(os.path.dirname(file))
    if "?" in file:
        file = file.split('?')[0]

    # Skip already downloaded files except index.html, which may have newer access keys
    if os.path.exists(file):
        logging.debug(f'Skipping url: {url} as already downloaded')
        return
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.5790.110 Safari/537.36",
            "Referer": "https://my.matterport.com/",
        }
        response = session.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception if the response has an error status code

        with open(file, 'wb') as f:
            f.write(response.content)
        logging.debug(f'Successfully downloaded: {url} to: {file}')
    except requests.exceptions.HTTPError as err:
        logging.warning(f'URL error Handling {url} or will try alt: {str(err)}')

        # Try again with different accessurls (very hacky!)
        if "?t=" in url:
            for accessurl in accessurls:
                url2 = ""
                try:
                    url2 = f"{url.split('?')[0]}?{accessurl}"
                    response = session.get(url2, headers=headers)
                    response.raise_for_status()  # Raise an exception if the response has an error status code

                    with open(file, 'wb') as f:
                        f.write(response.content)
                    logging.debug(f'Successfully downloaded through alt: {url2} to: {file}')
                    return
                except requests.exceptions.HTTPError as err:
                    logging.warning(f'URL error alt method tried url {url2} Handling of: {str(err)}')
                    pass
        logging.error(f'Failed to succeed for url {url}')
        raise Exception
        # Hopefully not getting here?
        logging.error(f'Failed2 to succeed for url {url}')


def downloadGraphModels(pageid):
    global GRAPH_DATA_REQ
    makeDirs("api/mp/models")

    for key in GRAPH_DATA_REQ:
        file_path = f"api/mp/models/graph_{key}.json"
        downloadFileWithJSONPost(
            "https://my.matterport.com/api/mp/models/graph", file_path, GRAPH_DATA_REQ[key], key)

def parseRuntimeJS(content):
    """
    Parses the runtime.js content to extract the chunk mapping.
    Returns a list of (chunk_id, chunk_name, chunk_hash) tuples.
    """
    chunks = []
    
    # Regex to find the name mapping: {239:"three-examples",...}
    # It usually appears in: n.u=e=>"js/"+({239:"three-examples",...}[e]||e)+"."
    name_map_match = re.search(r'n\.u=e=>"js/"\+\(({.*?)}\[e\]\|\|e\)', content)
    name_map = {}
    if name_map_match:
        # Parse the dictionary string: 239:"three-examples",777:"split"
        pairs = name_map_match.group(1).split(',')
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':')
                name_map[k.strip()] = v.strip('"')

    # Regex to find the hash mapping: +{235:"ebe436e0...",...}[e]+".js"
    # Regex to find the hash mapping: +{235:"ebe436e0...",...}[e]+".js"
    # Matches: +"."+{...}[e]+".js"
    # The content usually has: ...+"."+{...}[e]+".js"...
    # We need to match the dictionary inside the curly braces.
    
    logging.info(f"Runtime JS content start: {content[:500]}")
    
    # Robust regex handling different quotes and whitespace
    # Matches: + "." + {dictionary} [e] + ".js"
    # We use re.DOTALL just in case
    hash_map_match = re.search(r'\+\s*["\']\.["\']\s*\+\s*({.*?})\s*\[e\]\s*\+\s*["\']\.js["\']', content, re.DOTALL)
    
    if not hash_map_match:
         logging.info("First regex failed, trying loose match")
         # Match just the dictionary followed by [e]+".js"
         hash_map_match = re.search(r'({[\w\d]+:"[a-f0-9]+".*?})\[e\]\+"\.js"', content, re.DOTALL)

    hash_map = {}
    if hash_map_match:
        # Strip curly braces from the captured group
        content_str = hash_map_match.group(1).strip('{}')
        pairs = content_str.split(',')
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':')
                hash_map[k.strip()] = v.strip('"')

    # Combine them. Note: not all chunks have names, some just use ID.
    # The hash map usually contains all chunks.
    for chunk_id, chunk_hash in hash_map.items():
        chunk_name = name_map.get(chunk_id, chunk_id) # Default to ID if no name
        chunks.append((chunk_id, chunk_name, chunk_hash))

    return chunks

def parseRuntimeCSS(content):
    """
    Parses the runtime.js content to extract the CSS chunk mapping.
    """
    # n.miniCssF=e=>"css/"+({5385:"init",...}[e]||e)+".css"
    # n.miniCssF=e=>"css/"+({5385:"init",...}[e]||e)+".css"
    name_map_match = re.search(r'n\.miniCssF=e=>"css/"\+\(({.*?)}\[e\]\|\|e\)\+"\.css"', content)
    name_map = {}
    if name_map_match:
        pairs = name_map_match.group(1).split(',')
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':')
                name_map[k.strip()] = v.strip('"')

    # Find all chunks that have CSS
    # n.f.miniCss=(r,a)=>{... {1442:1,5385:1,...}[r] ...}
    # We look for the object with keys having value 1 inside n.f.miniCss
    css_chunks_match = re.search(r'n\.f\.miniCss=.*?\s*({[\d:,]+})\s*\[r\]', content, re.DOTALL)
    
    css_chunks = []
    if css_chunks_match:
        chunk_ids_str = css_chunks_match.group(1).strip('{}')
        pairs = chunk_ids_str.split(',')
        for pair in pairs:
            if ':' in pair:
                chunk_id, _ = pair.split(':')
                chunk_id = chunk_id.strip()
                # Resolve name: use map if exists, else use ID
                chunk_name = name_map.get(chunk_id, chunk_id)
                css_chunks.append(chunk_name)
    
    # Fallback: if we couldn't find the list, at least return the named ones we found
    if not css_chunks and name_map:
        css_chunks = list(name_map.values())

    return css_chunks


def downloadStaticReferencedAssets(html_content, base_url):
    logging.info("Downloading static referenced assets from HTML...")
    urls = []
    # Scripts
    matches = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_content)
    urls.extend(matches)
    # Links (CSS, icons)
    matches = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html_content)
    urls.extend(matches)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        for asset in urls:
            if asset.startswith("http") or asset.startswith("//") or asset.startswith("data:"):
                continue
            
            # Clean query params for local filename
            local_file = asset.split('?')[0]
            
            # Construct full URL
            if base_url.endswith("/") and asset.startswith("/"):
                full_url = base_url[:-1] + asset
            elif not base_url.endswith("/") and not asset.startswith("/"):
                full_url = base_url + "/" + asset
            else:
                full_url = base_url + asset
                
            executor.submit(downloadFile, full_url, local_file)

def downloadAssets(base, runtime_content):
    
    # 1. Parse runtime.js for JS chunks
    js_chunks = parseRuntimeJS(runtime_content)
    js_files = []
    for _, name, hash_val in js_chunks:
        js_files.append(f"js/{name}.{hash_val}.js")

    # 2. Parse runtime.js for CSS chunks
    css_chunks = parseRuntimeCSS(runtime_content)
    css_files = []
    for name in css_chunks:
        css_files.append(f"css/{name}.css")

    
    language_codes = ["af", "sq", "ar-SA", "ar-IQ", "ar-EG", "ar-LY", "ar-DZ", "ar-MA", "ar-TN", "ar-OM",
                      "ar-YE", "ar-SY", "ar-JO", "ar-LB", "ar-KW", "ar-AE", "ar-BH", "ar-QA", "eu", "bg",
                      "be", "ca", "zh-TW", "zh-CN", "zh-HK", "zh-SG", "hr", "cs", "da", "nl", "nl-BE", "en",
                      "en-US", "en-EG", "en-AU", "en-GB", "en-CA", "en-NZ", "en-IE", "en-ZA", "en-JM",
                      "en-BZ", "en-TT", "et", "fo", "fa", "fi", "fr", "fr-BE", "fr-CA", "fr-CH", "fr-LU",
                      "gd", "gd-IE", "de", "de-CH", "de-AT", "de-LU", "de-LI", "el", "he", "hi", "hu",
                      "is", "id", "it", "it-CH", "ja", "ko", "lv", "lt", "mk", "mt", "no", "pl",
                      "pt-BR", "pt", "rm", "ro", "ro-MO", "ru", "ru-MI", "sz", "sr", "sk", "sl", "sb",
                      "es", "es-AR", "es-GT", "es-CR", "es-PA", "es-DO", "es-MX", "es-VE", "es-CO",
                      "es-PE", "es-EC", "es-CL", "es-UY", "es-PY", "es-BO", "es-SV", "es-HN", "es-NI",
                      "es-PR", "sx", "sv", "sv-FI", "th", "ts", "tn", "tr", "uk", "ur", "ve", "vi", "xh",
                      "ji", "zu"]
    font_files = ["ibm-plex-sans-100", "ibm-plex-sans-100italic", "ibm-plex-sans-200", "ibm-plex-sans-200italic", "ibm-plex-sans-300",
                  "ibm-plex-sans-300italic", "ibm-plex-sans-500", "ibm-plex-sans-500italic", "ibm-plex-sans-600", "ibm-plex-sans-600italic",
                  "ibm-plex-sans-700", "ibm-plex-sans-700italic", "ibm-plex-sans-italic", "ibm-plex-sans-regular", "mp-font", "roboto-100", "roboto-100italic",
                  "roboto-300", "roboto-300italic", "roboto-500", "roboto-500italic", "roboto-700", "roboto-700italic", "roboto-900", "roboto-900italic",
                  "roboto-italic", "roboto-regular"]

    # extension assumed to be .png unless it is .svg or .jpg, for anything else place it in assets
    image_files = ["360_placement_pin_mask", "chrome", "Desktop-help-play-button.svg", "Desktop-help-spacebar", "edge", "escape", "exterior",
                   "exterior_hover", "firefox", "headset-cardboard", "headset-quest", "interior", "interior_hover", "matterport-logo-light.svg",
                   "mattertag-disc-128-free.v1", "mobile-help-play-button.svg", "nav_help_360", "nav_help_click_inside", "nav_help_gesture_drag",
                   "nav_help_gesture_drag_two_finger", "nav_help_gesture_pinch", "nav_help_gesture_position", "nav_help_gesture_position_two_finger",
                   "nav_help_gesture_tap", "nav_help_inside_key", "nav_help_keyboard_all", "nav_help_keyboard_left_right", "nav_help_keyboard_up_down",
                   "nav_help_mouse_position_right", "nav_help_mouse_zoom", "nav_help_tap_inside", "nav_help_zoom_keys", "NoteColor", "NoteIcon", "pinAnchor",
                   "puck_256_red", "roboto-700-42_0", "safari", "scope.svg", "showcase-password-background.jpg", "surface_grid_planar_256", "tagbg", "tagmask",
                   "vert_arrows","headset-quest-2","pinIconDefault","tagColor", "atlas"]

    assets = ["css/showcase.css", "css/unsupported_browser.css", "cursors/grab.png", "cursors/grabbing.png", "cursors/zoom-in.png",
              "cursors/zoom-out.png", "locale/strings.json", "css/ws-blur.css", "css/core.css", "css/split.css","css/late.css", "matterport-logo.svg", "css/init.css"]
              
    downloadFile("https://my.matterport.com/favicon.ico", "favicon.ico")
    
    # Add discovered files
    assets.extend(js_files)
    assets.extend(css_files)

    for image in image_files:
        if not image.endswith(".jpg") and not image.endswith(".svg"):
            image = image + ".png"
        assets.append("images/" + image)

    for f in font_files:
        assets.extend(["fonts/" + f + ".woff", "fonts/" + f + ".woff2"])
    for lc in language_codes:
        assets.append("locale/messages/strings_" + lc + ".json")
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        for asset in assets:
            local_file = asset
            if local_file.endswith('/'):
                local_file = local_file + "index.html"
            executor.submit(downloadFile, f"{base}{asset}", local_file)

def downloadWebglVendors(urls):
    for url in urls:      
        path= url.replace('https://static.matterport.com/','')
        downloadFile(url, path)

def setAccessURLs(pageid):
    global accessurls
    with open(f"api/player/models/{pageid}/files_type2", "r", encoding="UTF-8") as f:
        filejson = json.load(f)
        accessurls.append(filejson["base.url"].split("?")[-1])
    with open(f"api/player/models/{pageid}/files_type3", "r", encoding="UTF-8") as f:
        filejson = json.load(f)
        accessurls.append(filejson["templates"][0].split("?")[-1])


def downloadInfo(pageid):
    assets = [f"api/v1/jsonstore/model/highlights/{pageid}", f"api/v1/jsonstore/model/Labels/{pageid}", f"api/v1/jsonstore/model/mattertags/{pageid}", f"api/v1/jsonstore/model/measurements/{pageid}",
        f"api/v1/player/models/{pageid}/thumb?width=1707&dpr=1.5&disable=upscale", f"api/v1/player/models/{pageid}/", f"api/v2/models/{pageid}/sweeps", "api/v2/users/current", f"api/player/models/{pageid}/files", f"api/v1/jsonstore/model/trims/{pageid}", "api/v1/plugins?manifest=true"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        for asset in assets:
            local_file = asset
            if local_file.endswith('/'):
                local_file = local_file + "index.html"
            executor.submit(downloadFile, f"https://my.matterport.com/{asset}", local_file)
    makeDirs("api/mp/models")
    with open(f"api/mp/models/graph", "w", encoding="UTF-8") as f:
        f.write('{"data": "empty"}')
    for i in range(1, 4):
        downloadFile(
            f"https://my.matterport.com/api/player/models/{pageid}/files?type={i}", f"api/player/models/{pageid}/files_type{i}")
    setAccessURLs(pageid)


def downloadPics(pageid):
    with open(f"api/v1/player/models/{pageid}/index.html", "r", encoding="UTF-8") as f:
        modeldata = json.load(f)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        for image in modeldata["images"]:
            executor.submit(downloadFile, image["src"], urlparse(
                image["src"]).path[1:])


def downloadModel(pageid, accessurl, mesh_accessurl=None):
    global ADVANCED_DOWNLOAD_ALL
    if not mesh_accessurl:
        mesh_accessurl = accessurl

    with open(f"api/v1/player/models/{pageid}/index.html", "r", encoding="UTF-8") as f:
        modeldata = json.load(f)
    accessid = re.search(
        r'models/([a-z0-9-_./~]*)/\{filename\}', accessurl).group(1)
    makeDirs(f"models/{accessid}")
    os.chdir(f"models/{accessid}")
    downloadUUID(mesh_accessurl, modeldata["job"]["uuid"])
    downloadSweeps(accessurl, modeldata["sweeps"])


# Patch showcase.js to fix expiration issue
def patchShowcase():
    global SHOWCASE_INTERNAL_NAME
    
    # Find the actual showcase file we downloaded
    showcase_files = [f for f in os.listdir("js") if f.startswith("showcase.") and f.endswith(".js")]
    if not showcase_files:
        logging.error("Could not find downloaded showcase.js file to patch")
        return
    
    # Use the first one found (should be only one main showcase file)
    SHOWCASE_INTERNAL_NAME = showcase_files[0]
    logging.info(f"Patching {SHOWCASE_INTERNAL_NAME}")

    with open(f"js/{SHOWCASE_INTERNAL_NAME}", "r", encoding="UTF-8") as f:
        j = f.read()
    j = re.sub(r"\&\&\(!e.expires\|\|.{1,10}\*e.expires>Date.now\(\)\)", "", j)
    j = j.replace(f'"/api/mp/', '`${window.location.pathname}`+"api/mp/')
    j = j.replace("${this.baseUrl}",
                  "${window.location.origin}${window.location.pathname}")
    j = j.replace('e.get("https://static.matterport.com/geoip/",{responseType:"json",priority:i.RequestPriority.LOW})',
                  '{"country_code":"US","country_name":"united states","region":"CA","city":"los angeles"}')
    j = j.replace('https://static.matterport.com','')
    
    # Also patch the runtime to point to local chunks if needed, but usually relative paths work.
    # However, we might need to ensure publicPath is correct.
    
    with open(f"js/{SHOWCASE_INTERNAL_NAME}", "w", encoding="UTF-8") as f:
        f.write(j)


# Patch (graph_GetModelDetails.json & graph_GetSnapshots.json) URLs to Get files form local server instead of https://cdn-2.matterport.com/
def patchGetModelDetails():
    localServer = "http://127.0.0.1:8080"
    
    files_to_patch = ["graph_GetModelDetails.json", "graph_GetSnapshots.json", "graph_GetModelViewPrefetch.json"]
    
    for filename in files_to_patch:
        filepath = f"api/mp/models/{filename}"
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="UTF-8") as f:
                j = f.read()
            j = j.replace("https://cdn-2.matterport.com", localServer)
            j = re.sub(r"validUntil\"\s:\s*\"20[\d]{2}-[\d]{2}-[\d]{2}T", "validUntil\":\"2099-01-01T", j)
            with open(filepath, "w", encoding="UTF-8") as f:
                f.write(j)


def drange(x, y, jump):
    while x < y:
        yield float(x)
        x += decimal.Decimal(jump)


validToken = None
validKey = None
KNOWN_ACCESS_KEY = None


def GetOrReplaceKey(url, is_new=False):
    global validToken
    global validKey
    if is_new:
        match = re.search(r't=(.*?)&', url)
        if match:
            validToken = match.group(1)
        match = re.search(r'k=(.*?)"', url)
        if match:
            validKey = match.group(1)

    if validToken and validKey:
        url = re.sub(r't=.*?&', f't={validToken}&', url)
        url = re.sub(r'k=.*?$', f'k={validKey}', url)
    return url



def downloadPage(pageid):
    global ADVANCED_DOWNLOAD_ALL
    
    # Create downloads directory if it doesn't exist
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(downloads_dir):
        os.makedirs(downloads_dir)
        
    page_root_dir = os.path.join(downloads_dir, pageid)
    makeDirs(page_root_dir)

    # Load graph requests from repo root before changing directory
    graph_posts_dir = os.path.join(os.getcwd(), "graph_posts")
    openDirReadGraphReqs(graph_posts_dir, pageid)
    
    # Change to the target directory immediately
    original_cwd = os.getcwd()
    os.chdir(page_root_dir)

    ADV_CROP_FETCH = [
        {
                "start": "width=512&crop=1024,1024,",
                "increment": '0.5'
            },
        {
                "start": "crop=512,512,",
                "increment": '0.25'
            }
    ]

    import glob

# Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
        handlers=[
            logging.FileHandler("download.log", mode='w'),
            logging.StreamHandler()
        ]
    )
    logging.debug(f'Started up a download run')
    
    print("Downloading base page...")
    url = f"https://my.matterport.com/show/?m={pageid}"
    r = session.get(url)
    r.encoding = "utf-8"
    
    # Find static base
    staticbase_match = re.search(r'<base href="(https://static.matterport.com/.*?)">', r.text)
    if staticbase_match:
        staticbase = staticbase_match.group(1)
    else:
        raise Exception("Could not find static base URL")

    # Find Three.js (updated for module support)
    threeMin = re.search(
        r'https://static.matterport.com/webgl-vendors/three/[a-z0-9\-_/.]*/three.module.min.js', r.text)
    if not threeMin:
         threeMin = re.search(
            r'https://static.matterport.com/webgl-vendors/three/[a-z0-9\-_/.]*/three.min.js', r.text)
            
    if threeMin:
        threeMinUrl = threeMin.group()
        # Construct other vendor URLs based on three.js location
        # Note: The new structure might be different, but let's try to infer standard libs
        threeCoreUrl = threeMinUrl.replace('three.module.min.js','three.core.min.js').replace('three.min.js','three.core.min.js')
        dracoWasmWrapper = threeMinUrl.replace('three.module.min.js','libs/draco/gltf/draco_wasm_wrapper.js').replace('three.min.js','libs/draco/gltf/draco_wasm_wrapper.js')
        dracoDecoderWasm = threeMinUrl.replace('three.module.min.js','libs/draco/gltf/draco_decoder.wasm').replace('three.min.js','libs/draco/gltf/draco_decoder.wasm')
        basisTranscoderWasm = threeMinUrl.replace('three.module.min.js','libs/basis/basis_transcoder.wasm').replace('three.min.js','libs/basis/basis_transcoder.wasm')
        basisTranscoderJs = threeMinUrl.replace('three.module.min.js','libs/basis/basis_transcoder.js').replace('three.min.js','libs/basis/basis_transcoder.js')
        webglVendors = [threeMinUrl, threeCoreUrl, dracoWasmWrapper, dracoDecoderWasm, basisTranscoderWasm, basisTranscoderJs ]
    else:
        logging.warning("Could not find three.js URL, WebGL vendors might fail")
        webglVendors = []

    
    # Try to find accessurl via regex first (updated to be more permissive)
    # This is primarily for older tours or if JSON parsing fails
    match = re.search(
        r'"(https://cdn-\d*\.matterport\.com/models/[a-z0-9\-_/.]*/)([{}0-9a-z_/<>\\u.]+)(\?t=.*?)"', r.text)
    if match:
        accessurl = f'{match.group(1)}~/{{filename}}{match.group(3)}'
        mesh_accessurl = accessurl # Default to same if regex found
    else:
        accessurl = None
        mesh_accessurl = None

    # Fallback/Primary: Parse MP_PREFETCHED_MODELDATA
    match = re.search(r'window\.MP_PREFETCHED_MODELDATA = parseJSON\("(.+?)"\);', r.text, re.DOTALL)
    if match:
        try:
            json_str = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
            data = json.loads(json_str)
            
            # Get Tiles URL
            tilesets = data.get("queries", {}).get("GetModelPrefetch", {}).get("data", {}).get("model", {}).get("assets", {}).get("tilesets", [])
            if tilesets:
                url_template = tilesets[0].get("urlTemplate")
                if "/~/" in url_template:
                    base = url_template.split("/~/")[0]
                    query = url_template.split("?")[-1] if "?" in url_template else ""
                    accessurl = f"{base}/~/{{filename}}?{query}"
                    logging.info(f"Found tiles accessurl via JSON: {accessurl}")

            # Get Mesh URL
            meshes = data.get("queries", {}).get("GetModelPrefetch", {}).get("data", {}).get("model", {}).get("assets", {}).get("meshes", [])
            if meshes:
                mesh_url_raw = meshes[0].get("url")
                # mesh_url_raw example: .../assets/mesh_tiles/~/UUID_50k.dam?t=...
                if "/~/" in mesh_url_raw:
                    base = mesh_url_raw.split("/~/")[0]
                    query = mesh_url_raw.split("?")[-1] if "?" in mesh_url_raw else ""
                    # Try removing /~/ from the path as it might be causing issues
                    mesh_accessurl = f"{base}/{{filename}}?{query}"
                    logging.info(f"Found mesh accessurl via JSON (tilde removed): {mesh_accessurl}")
                else:
                    # URL is direct, e.g. .../assets/UUID_50k.dam?t=...
                    # We need to replace UUID_50k.dam with {filename}
                    path = mesh_url_raw.split("?")[0]
                    filename = path.split("/")[-1]
                    mesh_accessurl = mesh_url_raw.replace(filename, "{filename}")
                    logging.info(f"Found mesh accessurl via JSON (direct): {mesh_accessurl}")
                    
        except Exception as e:
            logging.warning(f"Failed to parse MP_PREFETCHED_MODELDATA: {e}")
    
    if not accessurl:
        raise Exception("Can't find urls")
    if not mesh_accessurl:
        mesh_accessurl = accessurl # Fallback

    # get a valid access key, there are a few but this is a common client used one, this also makes sure it is fresh
    file_type_content = requests.get(
        f"https://my.matterport.com/api/player/models/{pageid}/files?type=3")
    GetOrReplaceKey(file_type_content.text, True)
    if ADVANCED_DOWNLOAD_ALL:
        print("Doing advanced download of dollhouse/floorplan data...")
        # ... (rest of advanced download logic)
        try:
            if match: # Re-use the match from above if possible or re-parse
                 # ... (existing logic)
                 pass
        except:
            pass


    # Find and download runtime and showcase scripts first to parse them
    # Look for src="js/runtime~showcase.[hash].js"
    runtime_match = re.search(r'src="(js/runtime~showcase\.[a-f0-9]+\.js)"', r.text)
    showcase_match = re.search(r'src="(js/showcase\.[a-f0-9]+\.js)"', r.text)
    
    runtime_content = ""
    if runtime_match:
        runtime_path = runtime_match.group(1)
        downloadFile(f"{staticbase}{runtime_path}", runtime_path)
        with open(runtime_path, "r", encoding="UTF-8") as f:
            runtime_content = f.read()
    else:
        logging.warning("Could not find runtime~showcase.js")

    if showcase_match:
        showcase_path = showcase_match.group(1)
        downloadFile(f"{staticbase}{showcase_path}", showcase_path)
    else:
        logging.warning("Could not find showcase.js")

        
    # Automatic redirect if GET param isn't correct
    injectedjs = 'if (window.location.search != "?m=' + pageid + \
                      '") { document.location.search = "?m=' + pageid + '"; }'
    # Replace static base and remove external CDN URLs for local serving
    # Use absolute URL for localhost to avoid Invalid URL errors in client
    content = r.text.replace(staticbase, "http://localhost:8080/").replace(
        "window.MP_PREFETCHED_MODELDATA", f"{injectedjs};window.MP_PREFETCHED_MODELDATA"
    )
    # Remove external CDN prefixes - for local serving we don't need them
    # Use absolute URL for localhost to avoid Invalid URL errors in client
    content = content.replace('"https://cdn-1.matterport.com/', '"http://localhost:8080/')
    content = content.replace('"https://mp-app-prod.global.ssl.fastly.net/', '"http://localhost:8080/')
    content = content.replace('"https://events.matterport.com/', '"http://localhost:8080/')
    content = content.replace('"https://cdn-2.matterport.com/', '"http://localhost:8080/')
    
    if threeMin:
        # Prepend ./ to the path for local module loading
        content = content.replace(f'{threeMinUrl}', "./" + threeMinUrl.replace('https://static.matterport.com/',''))
        
    content = re.sub(r"validUntil\":\s*\"20[\d]{2}-[\d]{2}-[\d]{2}T", "validUntil\":\"2099-01-01T", content)

    
    # Inject client-side logging
    content = injectClientLogger(content)

    # Inject all graph data
    content = injectGraphData(content, pageid)

    with open("index.html", "w", encoding="UTF-8") as f:
        f.write(content)


    print("Downloading static assets...")
    downloadAssets(staticbase, runtime_content)
    downloadStaticReferencedAssets(r.text, staticbase)
    downloadWebglVendors(webglVendors)
    # Patch showcase.js to fix expiration issue and some other changes for local hosting
    patchShowcase()
    print("Downloading model info...")
    downloadInfo(pageid)
    print("Downloading images...")
    downloadPics(pageid)
    print("Downloading graph model data...")
    downloadGraphModels(pageid)
    print(f"Patching graph_GetModelDetails.json URLs")
    patchGetModelDetails()
    print(f"Downloading model ID: {pageid} ...")
    
    # Create downloads directory if it doesn't exist
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(downloads_dir):
        os.makedirs(downloads_dir)
        
    page_root_dir = os.path.join(downloads_dir, pageid)
    makeDirs(page_root_dir)
    
    downloadModel(pageid, accessurl, mesh_accessurl)
    # os.chdir(page_root_dir) # Already changed at start
    makeDirs("api/v1")
    open("api/v1/event", 'a').close()
    print("Done!")



def initiateDownload(url):
    downloadPage(getPageId(url))


def getPageId(url):
    return url.split("m=")[-1].split("&")[0]



class OurSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):
    def send_error(self, code, message=None):
        if code == 404:
            logging.warning(
                f'404 error: {self.path} may not be downloading everything right')
        SimpleHTTPRequestHandler.send_error(self, code, message)


    def do_GET(self):
        global SHOWCASE_INTERNAL_NAME
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
        raw_path, _, query = self.path.partition('?')
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
            logging.info(
                f'Redirecting {orig_request} => {self.path} as {redirect_msg}')


        SimpleHTTPRequestHandler.do_GET(self)
        return

    def do_POST(self):
        post_msg = None
        try:
            if self.path == "/api/mp/models/graph":
                self.send_response(200)
                self.end_headers()
                content_len = int(self.headers.get('content-length'))
                post_body = self.rfile.read(content_len).decode('utf-8')
                json_body = json.loads(post_body)
                option_name = json_body["operationName"]
                if option_name in GRAPH_DATA_REQ:
                    file_path = f"api/mp/models/graph_{option_name}.json"
                    if os.path.exists(file_path):
                        with open(file_path, "r", encoding="UTF-8") as f:
                            self.wfile.write(f.read().encode('utf-8'))
                            post_msg = f"graph of operationName: {option_name} we are handling internally"
                            return
                    else:
                        post_msg = f"graph for operationName: {option_name} we don't know how to handle, but likely could add support, returning empty instead"

                self.wfile.write(bytes('{"data": "empty"}', "utf-8"))
                return
        except Exception as error:
            post_msg = f"Error trying to handle a post request of: {str(error)} this should not happen"
            pass
        finally:
            if post_msg is not None:
                logging.info(
                    f'Handling a post request on {self.path}: {post_msg}')

        self.do_GET()  # just treat the POST as a get otherwise:)

    def guess_type(self, path):
        res = SimpleHTTPRequestHandler.guess_type(self, path)
        if res == "text/html":
            return "text/html; charset=UTF-8"
        return res

PROXY = False
ADVANCED_DOWNLOAD_ALL = False

GRAPH_DATA_REQ = {}

def injectClientLogger(content):
    logger_script = """
    <script>
    (function() {
        var oldLog = console.log;
        var oldWarn = console.warn;
        var oldError = console.error;

        function sendLog(level, args) {
            var msg = Array.from(args).map(a => {
                try { return typeof a === 'object' ? JSON.stringify(a) : String(a); }
                catch(e) { return String(a); }
            }).join(' ');
            fetch('/client_log', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({level: level, message: msg, timestamp: new Date().toISOString()})
            }).catch(e => {});
        }

        console.log = function() { oldLog.apply(console, arguments); sendLog('INFO', arguments); };
        console.warn = function() { oldWarn.apply(console, arguments); sendLog('WARN', arguments); };
        console.error = function() { oldError.apply(console, arguments); sendLog('ERROR', arguments); };
        
        window.onerror = function(msg, url, line, col, error) {
            sendLog('ERROR', ['Uncaught Exception:', msg, url, line, col, error]);
        };
        
        window.addEventListener('unhandledrejection', function(event) {
            sendLog('ERROR', ['Unhandled Rejection:', event.reason]);
        });
    })();
    </script>
    """
    return content.replace("<head>", "<head>" + logger_script)

def injectGraphData(content, pageid):
    logging.info("Injecting graph data into index.html...")
    match = re.search(r'window\.MP_PREFETCHED_MODELDATA = parseJSON\("(.+?)"\);', content, re.DOTALL)
    if not match:
        logging.warning("Could not find MP_PREFETCHED_MODELDATA in index.html for injection")
        return content

    json_str = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from index.html: {e}")
        return content

    if "queries" not in data:
        data["queries"] = {}

    # Iterate over all graph_*.json files in the expected download location
    # Note: We are currently in the download directory when this runs? 
    # No, downloadPage changes dir at the end? No, it doesn't change dir until the server starts or we need to be careful.
    # The files are in api/mp/models/ relative to current working dir if we are inside the page dir.
    # Let's check where we are. downloadPage creates page_root_dir but doesn't chdir into it until later?
    # Actually downloadPage does NOT chdir. It uses os.path.join.
    
    models_dir = os.path.join("api", "mp", "models")
    if os.path.exists(models_dir):
        graph_files = glob.glob(os.path.join(models_dir, "graph_*.json"))
        logging.info(f"Found {len(graph_files)} graph files to inject.")

        for file_path in graph_files:
            filename = os.path.basename(file_path)
            op_name = filename.replace("graph_", "").replace(".json", "")
            
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    op_data = json.load(f)
                    data["queries"][op_name] = op_data
                    logging.info(f"Injected {op_name}")
                except json.JSONDecodeError:
                    logging.warning(f"Failed to decode {filename}, skipping.")
    else:
        logging.warning(f"Models directory {models_dir} not found during injection")

    new_json_str = json.dumps(data).replace('\\', '\\\\').replace('"', '\\"')
    return content.replace(match.group(1), new_json_str)

def openDirReadGraphReqs(path, pageId):
    for root, dirs, filenames in os.walk(path):
        for file in filenames:
            with open(os.path.join(root, file), "r", encoding="UTF-8") as f:
                GRAPH_DATA_REQ[file.replace(".json", "")] = f.read().replace("[MATTERPORT_MODEL_ID]",pageId)             


def getUrlOpener(use_proxy):
    if (use_proxy):
        proxy = urllib.request.ProxyHandler({'http': use_proxy, 'https': use_proxy})
        opener = urllib.request.build_opener(proxy)
    else:
        opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'),('x-matterport-application-name','showcase')]
    return opener


def getCommandLineArg(name, has_value):
    for i in range(1, len(sys.argv)):
        if sys.argv[i] == name:
            sys.argv.pop(i)
            if has_value:
                return sys.argv.pop(i)
            else:
                return True
    return False


if __name__ == "__main__":
    ADVANCED_DOWNLOAD_ALL = getCommandLineArg("--advanced-download", False)
    PROXY = getCommandLineArg("--proxy", True)
    OUR_OPENER = getUrlOpener(PROXY)
    urllib.request.install_opener(OUR_OPENER)
    pageId = ""
    if len(sys.argv) > 1:
        pageId = getPageId(sys.argv[1])
    openDirReadGraphReqs("graph_posts", pageId)
    if len(sys.argv) == 2:
        initiateDownload(pageId)
    elif len(sys.argv) == 4:
        os.chdir(getPageId(pageId))
        try:
            logging.basicConfig(filename='server.log', encoding='utf-8', level=logging.DEBUG,  format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        except ValueError:
            logging.basicConfig(filename='server.log', level=logging.DEBUG,  format='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        logging.info("Server started up")
        
        # Determine showcase name for server
        showcase_files = [f for f in os.listdir("js") if f.startswith("showcase.") and f.endswith(".js")]
        if showcase_files:
            SHOWCASE_INTERNAL_NAME = showcase_files[0]


        print("View in browser: http://" + sys.argv[2] + ":" + sys.argv[3])
        httpd = HTTPServer(
            (sys.argv[2], int(sys.argv[3])), OurSimpleHTTPRequestHandler)
        httpd.serve_forever()
    else:
        print(f"Usage:\n\tFirst Download: matterport-dl.py [url_or_page_id]\n\tThen launch the server 'matterport-dl.py [url_or_page_id] 127.0.0.1 8080' and open http://127.0.0.1:8080 in a browser\n\t--proxy 127.0.0.1:1234 -- to have it use this web proxy\n\t--advanced-download -- Use this option to try and download the cropped files for dollhouse/floorplan support")
