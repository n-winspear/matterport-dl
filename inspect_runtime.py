import glob
import os

# Find the runtime file
files = glob.glob("AxN4GbV5ko7/js/runtime~showcase*.js")
if not files:
    files = glob.glob("downloads/AxN4GbV5ko7/js/runtime~showcase*.js")
if files:
    print(f"Found file: {files[0]}")
    with open(files[0], 'r') as f:
        content = f.read()
        
        # Find the part with chunk mapping
        # Look for n.u=
        idx = content.find('n.u=')
        if idx != -1:
            print("Found n.u= at index", idx)
            print("Context around n.u=:")
            print(content[idx:idx+1000])
        else:
            print("Could not find n.u=")
            
        # Look for the hash mapping part: +{...}[e]+".js"
        # It usually follows the name mapping
        # Try to find the second dictionary
        # Look for "+"."+
        idx2 = content.find('"+"."+')
        if idx2 != -1:
            print("Found \"+\".\"+ at index", idx2)
            print("Context around \"+\".\"+:")
            print(content[idx2:idx2+1000])
        else:
             print("Could not find \"+\".\"+")
else:
    print("No runtime file found")
