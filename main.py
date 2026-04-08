import asyncio
import os
import enum
import json

import pyppeteer
import httpx
import aiofiles
import hydrogram as pyrogram

MAX_REFRESH_TIME = 60 * 1
EXTENSIONS_INDEX_URL = "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"

ETAG_FILE = os.path.join(os.getcwd(), "etag.txt")
EXTENSIONS_FILE = os.path.join(os.getcwd(), "extensions.json")

REPOSITORY_URL = "https://github.com/keiyoushi/extensions-source"
REPOSITORY_DIRECTORY = os.path.join(os.getcwd(), "submodules/tachiyomi-extensions")

CHAT_ID = "@NikAnimes"

class Status(enum.Enum):
	STATUS_EXTENSION_REMOVED = 1
	STATUS_EXTENSION_ADDED = 2

async def find_commit(body, directory):
	
	process = await asyncio.create_subprocess_shell(
		cmd = " ".join([
			"git",
			"--git-dir=%s/.git" % directory,
			"--work-tree=%s" % directory,
			"pull"
		])
	)
	
	await process.communicate()
	assert process.returncode == 0
	
	process = await asyncio.create_subprocess_shell(
		cmd = " ".join([
			"git",
			"--git-dir=%s/.git" % directory,
			"--work-tree=%s" % directory,
			"log",
			"--pretty=format:%h"
		]),
		stdout = asyncio.subprocess.PIPE
	)
	
	(stdout, stderr) = await process.communicate()
	assert process.returncode == 0
	
	output = stdout.decode()
	
	commits = output.split()[0:100]
	
	for commit in commits:
		process = await asyncio.create_subprocess_shell(
			cmd = " ".join([
				"git",
				"--git-dir=%s/.git" % directory,
				"--work-tree=%s" % directory,
				"diff",
				"%s~" % commit,
				commit
			]),
			stdout = asyncio.subprocess.PIPE
		)
		
		(stdout, stderr) = await process.communicate()
		assert process.returncode == 0
		
		output = stdout.decode()
		
		if body in output:
			return commit
	
	return None

async def main():
	
	pyrogram_options = {
		"name": "bot",
		"api_id": 105810,
		"api_hash": "3e7a52498eec003c5896a330e5d29397",
		"no_updates": True
	}
	
	telegc = pyrogram.Client(**pyrogram_options)
	
	headers = {}
	current_extensions = []
	
	if os.path.exists(path = ETAG_FILE):
		async with aiofiles.open(file = ETAG_FILE, mode = "r") as file:
			text = await file.read()
		
		headers.update(
			{
				"If-None-Match": text
			}
		)
	
	if os.path.exists(path = EXTENSIONS_FILE):
		async with aiofiles.open(file = EXTENSIONS_FILE, mode = "r") as file:
			text = await file.read()
		
		current_extensions = json.loads(s = text)
	
	browser = await pyppeteer.launch(args = ["--no-sandbox"])
	context = await browser.createIncognitoBrowserContext()
	
	page = await context.newPage()
	
	await page.setViewport(
		viewport = {
			"width": 1280,
			"height": 720
		}
	)
	
	await telegc.start()
	
	async with httpx.AsyncClient(http2 = True) as client:
		while True:
			print("- Fetching data from %s" % (EXTENSIONS_INDEX_URL))
			
			response = await client.get(
				url = EXTENSIONS_INDEX_URL,
				headers = headers
			)
			
			if response.status_code == 304:
				await asyncio.sleep(MAX_REFRESH_TIME)
				continue
			
			items = response.json()
			
			latest_extensions = []
			
			for item in items:
				(item_name, item_package_name, item_language) = (
					item["name"].removeprefix("Tachiyomi: "),
					item["pkg"],
					item["lang"],
				)
				
				latest_extensions.append(
					{
						"name": item_name,
						"language": item_language,
						"package_name": item_package_name
					}
				)
			
			if current_extensions:
				removed_extensions = []
				added_extensions = []
				
				# Check for removed extensions
				for current_extension in current_extensions:
					exists = False
					
					for latest_extension in latest_extensions:
						exists = current_extension["package_name"] == latest_extension["package_name"]
						
						if exists:
							break
					
					if not exists:
						# Extension got isekaied :<
						removed_extensions.append(current_extension)
				
				# Check for new extensions
				for latest_extension in latest_extensions:
					exists = False
					
					for current_extension in current_extensions:
						exists = latest_extension["package_name"] == current_extension["package_name"]
						
						if exists:
							break
					
					if not exists:
						# Someone added a new extension :O
						added_extensions.append(latest_extension)
				
				queue = []
				
				tree = {
					"added_extensions": added_extensions,
					"removed_extensions": removed_extensions
				}
				
				for key in tree.keys():
					if key == "added_extensions":
						status = Status.STATUS_EXTENSION_ADDED
					else:
						status = Status.STATUS_EXTENSION_REMOVED
					
					items = tree[key]
					
					for item in items:
						(extension_name, extension_language, extension_package_name) = (
							item["name"],
							item["language"],
							item["package_name"],
						)
						
						for body in (extension_package_name, extension_name):
							commit = await find_commit(
								body = body,
								directory = REPOSITORY_DIRECTORY
							)
							
							if commit is not None:
								break
						
						if commit is None:
							commit = "HEAD"
						
						queue.append(
							{
								"status": status,
								"name": extension_name,
								"language": extension_language,
								"package_name": extension_package_name,
								"commit": commit
							}
						)
				
				for item in queue:
					(extension_status, extension_name, extension_language, extension_package_name, commit) = (
						item["status"],
						item["name"],
						item["language"],
						item["package_name"],
						item["commit"]
					)
					
					commit_url = "%s/commit/%s" % (REPOSITORY_URL, commit)
					
					caption = "%s **%s** (`%s`) has been %s Tachiyomi's extensions repository!" % (
						"🔴" if extension_status == Status.STATUS_EXTENSION_REMOVED else "🟢",
						extension_name,
						extension_language,
						"removed from" if extension_status == Status.STATUS_EXTENSION_REMOVED else "added to"
					)
					
					await page.goto(
						url = commit_url,
						waitUntil = [
							"domcontentloaded",
							"networkidle2"
						]
					)
					
					path = "./screenshot.jpg"
					
					await page.screenshot(
						options = {
							"path": path,
							"type": "jpeg",
							"quality": 100
						}
					)
					
					await telegc.send_photo(
						chat_id = CHAT_ID,
						photo = path,
						caption = caption,
						reply_markup = pyrogram.types.InlineKeyboardMarkup(
							inline_keyboard = [
								[
									pyrogram.types.InlineKeyboardButton(
										text = "View on GitHub",
										url = commit_url
									)
								]
							]
						)
					)
			
			current_extensions = latest_extensions
			
			text = json.dumps(obj = current_extensions)
			
			async with aiofiles.open(file = EXTENSIONS_FILE, mode = "w") as file:
				await file.write(text)
			
			etag = response.headers["Etag"]
			
			headers.update(
				{
					"If-None-Match": etag
				}
			)
			
			async with aiofiles.open(file = ETAG_FILE, mode = "w") as file:
				await file.write(etag)
			
			await asyncio.sleep(MAX_REFRESH_TIME)

event_policy = asyncio.get_event_loop_policy()
event_loop = event_policy.new_event_loop()
event_loop.run_until_complete(main())