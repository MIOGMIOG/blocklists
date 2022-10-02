import os
import errno
import json
import random
import re
import sys
import urllib.request
from urllib.parse import urlparse
import asyncio
import aiohttp

supportedFileFormat = {"domains", "hosts", "abp", "wildcard"}

isConfigLoad = False
keyFormat = {"vname",  "format", "group", "subg", "url", "pack"}
configFileLocation = "./blocklistConfig.json"
vnameMapFileLocation = "./valueUnameMap.json"
unameVnameMap = {}
configDict = {}
urlExist = set()
valueExist = set()
unameExist = set()

totalUrl = 0
savedUrl = 0

blocklistfiles = os.environ.get("INDIR")
blocklistDownloadRetry = 3
blocklistNotDownloaded = list()
retryBlocklist = list()

def validateBasicConfig():
    global keyFormat
    index = 0
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    for value in configDict["conf"]:
        if len(value) != len(keyFormat):
            print ("Invalid Blocklist config Format")
            print (value)
            print ("Should contain below fields")
            print (keyFormat)
            return False

        if not keyFormat <= set(value):
            print ("Invalid key format")
            print (value)
            return False


        if re.match(regex, value["url"]) is None:
            print ("Invalid url format")
            print (value)
            return False

        if value["url"] in urlExist:
            print ("Url Already Exist in Blocklist config json")
            print (value)
            return False
        else:
            urlExist.add(value["url"])


        if not value["format"] in supportedFileFormat:
            print ("Added file format not supported currently")
            print (value)
            return False

        if value["group"].strip() == "":
            print ("group name mandatory")
            print (value)
            return False

        value["index"] = index
        index = index + 1
    random.shuffle(configDict["conf"])
    return True

async def parseDownloadBasicConfig(configList):
    global totalUrl
    global unameVnameMap
    global blocklistNotDownloaded
    global retryBlocklist
    global blocklistfiles

    downloadLoc = ""
    totalUrl = 0
    fileName = ""

    # realpython.com/python-concurrency/#asyncio-version
    async with aiohttp.ClientSession() as sess:
        tasks = []
        for value in configList:
            if str(value["index"]) in unameVnameMap:
                fileName = unameVnameMap[str(value["index"])]
            else:
                fileName = str(value["index"])

            if value["subg"].strip() == "":
                downloadLoc = "./" + blocklistfiles + "/" + value["group"].strip() + "/" + fileName + ".txt"
            else:
                downloadLoc = "./" + blocklistfiles + "/" + value["group"].strip() + "/"  + value["subg"].strip() + "/" + fileName + ".txt"

            if('dead' in value["pack"]):
                totalUrl = totalUrl + 1
                print("\n" + str(totalUrl) + "; dead -> skip download")
                print(f"{value}\n")
                continue

            task = asyncio.ensure_future(downloadFile(sess, value["url"], value["format"], downloadLoc))
            tasks.append(task)

        # docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently
        rets = await asyncio.gather(*tasks, return_exceptions=True)

        for ret in rets:
            if (not ret) and ('ignore' in value["pack"]):
                blocklistNotDownloaded.append(str(value))
                print("\n")
            elif ret == "retry":
                retryBlocklist.append(value)
            elif not ret:
                print("\n\nblocklist not downloaded:")
                print(value)
                print("\n")
                # FIXME: continue with warning
                # sys.exit("")

def createFileNotExist(filename):
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

def safeStr(obj):
    try: return str(obj)
    except UnicodeEncodeError:
        return obj.encode('ascii', 'ignore').decode('ascii')

def regxFileDomain(txt,regx_str,grp_index,format):
    domainlist = set()
    abp_regx = re.compile(regx_str,re.M)
    for match in re.finditer(abp_regx, txt):
        g2 = match.groups()[grp_index]
        g2 = g2.strip()
        if g2 and g2[-1]!='.':
            domainlist.add(g2)

    if format != "wildcard" and len(domainlist) <= 8:
        return ""

    return "\n".join(domainlist)

def writeFile(download_loc_filename,filetxt):
    global savedUrl
    if filetxt and filetxt != "":
        createFileNotExist(download_loc_filename)
        with open(download_loc_filename, "w") as f:
            f.write(safeStr(filetxt))
            f.close()
        savedUrl = savedUrl + 1
        return True
    else:
        return False

def urllibRequestApi(url):
    try:
        response = urllib.request.urlopen(url)
        data = response.read()
        r = data.decode('utf-8')
        return r
    except Exception as e:
        print("Exception")
        print(e)
        return False

# docs.aiohttp.org/en/stable/
async def requestApi(session, url):
    async with session.get(url) as response:
        if response.status == 200:
            return await response.text()
        else:
            raise(DownloadFailed(f"downloading {url} failed; status: {response.status}"))

# stackoverflow.com/a/7957799
class DownloadFailed(Exception):
    pass

# realpython.com/async-io-python/
async def downloadFile(sess, url, format, download_loc_filename):
    global totalUrl
    totalUrl = totalUrl + 1
    print (str(totalUrl) + "; src: " + url + " | dst: " + download_loc_filename)
    ret = True
    f = True

    try:
        f = await requestApi(sess, url)
    except Exception as e:
        print(f"\nErr downloading {url}\n{e}")
        return "retry"

    if format == "domains" or format == "wildcard":
        filetxt = regxFileDomain(f, r'(^[a-zA-Z0-9][a-zA-Z0-9-_.]+)',0,format)
    elif format == "hosts":
        filetxt = regxFileDomain(f, r'(^([0-9]{1,3}\.){3}[0-9]{1,3})([ \t]+)([a-zA-Z0-9-_.]+)',3,format)
    elif format == "abp":
        filetxt = regxFileDomain(f, r'^(\|\||[a-zA-Z0-9])([a-zA-Z0-9][a-zA-Z0-9-_.]+)((\^[a-zA-Z0-9\-\|\$\.\*]*)|(\$[a-zA-Z0-9\-\|\.])*|(\\[a-zA-Z0-9\-\||\^\.]*))$',1,format)

    ret = writeFile(download_loc_filename, filetxt)

    if not ret:
        print("\n\nDownloaded file empty or has <=10 entries\n")
        print(url + " : " + download_loc_filename + "\n")

    return ret

def loadBlocklistConfig():
    global isConfigLoad
    global configDict
    global unameVnameMap

    try:
        if os.path.isfile(configFileLocation):
            with open(configFileLocation) as json_file:
                configDict = json.load(json_file)
                json_file.close()
                if "conf" in configDict:
                    isConfigLoad = True
        if not isConfigLoad:
            configDict["conf"] = {}

        if os.path.isfile(vnameMapFileLocation):
            with open(vnameMapFileLocation) as json_file:
                unameVnameMap = json.load(json_file)
                json_file.close()
    except:
        print("Error parsing blocklist.json. Check json format")
        sys.exit("Error")


def main():
    global totalUrl
    global savedUrl
    global blocklistNotDownloaded
    global configDict
    global retryBlocklist

    tmpRetryBlocklist = list()
    loadBlocklistConfig()
    exitWithError = False

    if isConfigLoad:
        if validateBasicConfig():
            asyncio.run(parseDownloadBasicConfig(configDict["conf"]))

            print("\nTotal blocklists: " + str(totalUrl))
            print("Saved blocklists: " + str(savedUrl))
            print("Difference: " + str(totalUrl - savedUrl))

            if len(retryBlocklist) >= 1:
                print("\n\nretry download blocklist\n\n")
                tmpRetryBlocklist = retryBlocklist
                retryBlocklist = list()
                asyncio.run(parseDownloadBasicConfig(tmpRetryBlocklist))

            print("\n\nFailed download list:")
            print("\n".join(blocklistNotDownloaded))

            if len(retryBlocklist) >= 1:
                print ("\nError downloading blocklist\n")
                for value in retryBlocklist:
                    if not ('ignore' in value["pack"]):
                        exitWithError = True
                    print(f"{value}\n")
                if exitWithError:
                    sys.exit("")
        else:
            print("Validation Error")
            sys.exit("")
    else:
        print("Error loading config, download aborted.")

if __name__ == "__main__":
    main()
