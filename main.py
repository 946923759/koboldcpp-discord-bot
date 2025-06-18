#!/usr/bin/env python3
import sys
import os
import discord
from discord.ext import commands
import json
from typing import Dict, Any, Tuple, Optional, List, TypedDict, Deque, Union
from collections import deque
import aiohttp
from aiohttp import web
from glob import glob
from PIL import Image
import base64
from io import BytesIO

class TavernCardV2Data(TypedDict):
	name: str
	description: str
	personality: str
	scenario: str
	first_mes: str
	mes_example: str
	creator_notes: str
	system_prompt: str
	post_history_instructions: str
	alternate_greetings: List[str]
	character_book: Optional['CharacterBook']
	tags: List[str]
	creator: str
	character_version: str
	extensions: Dict[str, Any]

class TavernCardV2(TypedDict):
	spec: str
	spec_version: str
	data: TavernCardV2Data

class CharacterBookEntry(TypedDict):
	keys: List[str]
	content: str
	extensions: Dict[str, Any]
	enabled: bool
	insertion_order: int
	case_sensitive: Optional[bool]
	name: Optional[str]
	priority: Optional[int]
	id: Optional[int]
	comment: Optional[str]
	selective: Optional[bool]
	secondary_keys: Optional[List[str]]
	constant: Optional[bool]
	position: Optional[str]

class CharacterBook(TypedDict):
	name: Optional[str]
	description: Optional[str]
	scan_depth: Optional[int]
	token_budget: Optional[int]
	recursive_scanning: Optional[bool]
	extensions: Dict[str, Any]
	entries: List[CharacterBookEntry]

class KoboldCPPData(TypedDict):
	n: int
	max_context_length: int
	max_length: int
	rep_pen: float
	temperature: float
	top_p: float
	top_k: float
	top_a: float
	typical: int
	tfs: int
	rep_pen_range: int
	rep_pen_slope: float
	sampler_order: List[int]
	memory: str
	trim_stop: bool
	genkey: str
	min_p: int
	dynatemp_range: int
	dynatemp_exponent: int
	smoothing_factor: int
	nsigma: int
	banned_tokens: List[str]
	render_special: bool
	logprobs: bool
	replace_instruct_placeholders: bool
	presence_penalty: int
	logit_bias: dict
	prompt: str
	quiet: bool
	stop_sequence: List[str]
	use_default_badwordsids: bool
	bypass_eos: bool

if 'DISCORD_TOKEN' not in os.environ:
	print("Please add your bot's token to environment variables as DISCORD_TOKEN so the bot can read it")
	sys.exit(1)

TOKEN = os.environ['DISCORD_TOKEN']
KOBOLDCPP_API_ENDPOINT = "http://localhost:5001/api/v1/generate"


# Enable intents for message content reading.
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # Required to read message content

# Create the bot instance with a command prefix (here "!" is arbitrary)
bot = commands.Bot(command_prefix='!', intents=intents)

message_history:Deque[str] = deque(maxlen=50)
character_data:TavernCardV2 = {} #type: ignore
koboldcpp_data:KoboldCPPData = {
	"n": 1,
	"max_context_length": 4096,
	"max_length": 512,
	"rep_pen": 1.07,
	"temperature": 0.75,
	"top_p": 0.92,
	"top_k": 100,
	"top_a": 0,
	"typical": 1,
	"tfs": 1,
	"rep_pen_range": 360,
	"rep_pen_slope": 0.7,
	"sampler_order": [
		6,
		0,
		1,
		3,
		4,
		2,
		5
	],
	"memory": "",
	"trim_stop": True,
	"genkey": "KCPP3039",
	"min_p": 0,
	"dynatemp_range": 0,
	"dynatemp_exponent": 1,
	"smoothing_factor": 0,
	"nsigma": 0,
	"banned_tokens": [],
	"render_special": False,
	"logprobs": False,
	"replace_instruct_placeholders": True,
	"presence_penalty": 0,
	"logit_bias": {},
	"prompt": "",
	"quiet": True,
	"stop_sequence": [
		"User:",
		"\nUser ",
		"\nREPLACE_THIS_VALUE_WITH_CHARACTER_NAME: " #This gets replaced on load, don't worry about it
	],
	"use_default_badwordsids": False,
	"bypass_eos": False
}

def generate_koboldcpp_memory_tag(data:TavernCardV2Data, prompt:str, username:str="User") -> str:
	"""This generates the memory tag for a koboldcpp API prompt.
	The current prompt is required for the entries page. This will insert
	definitions for the character to respond better based on keywords in the message.
	"""
	memory:str = "Persona: "+data['description'] +"\n"
	memory    += "[Scenario: "+data['scenario'] +"]\n"
	memory    += data['mes_example']

	memory = memory.replace("{{char}}", data['name']).replace("{{user}}",username)

	if 'character_book' in data and data['character_book']:
		character_book:CharacterBook = data['character_book']
		memory    += "\n***"

		prompt_lowercase:str = prompt.lower()
		#Now insert definitions based on keywords...
		for entry in character_book['entries']:
			for key in entry['keys']:
				if key.lower() in prompt_lowercase:
					memory += "\n" + entry['content']
	
	return memory

async def contact_koboldcpp(message_history:Deque[str], character_data:TavernCardV2, username:str="User") -> str:
	"""Contacts Koboldcpp.
	This function will overwrite koboldcpp_data, but otherwise does not cause side effects.

	_return_: fuck you
	"""
	koboldcpp_data['stop_sequence'][0] = f"{username}:"
	#koboldcpp_data['stop_sequence'][1] = f"{username} "
	koboldcpp_data['stop_sequence'][2] = f"\n{character_data['data']['name']}:"

	#prompt:str = message_history[0]
	#for i in range(1, len(message_history)):
	#	prompt += "\n"+message_history[i]

	prompt:str = ""
	for message in message_history:
		prompt += message +"\n"
	prompt = prompt.replace("{{char}}", character_data['data']['name']).replace("{{user}}",username)
	print(prompt)
	print("---")

	#And this will instruct the LLM to complete the prompt...
	prompt += f"{character_data['data']['name']}:"
	koboldcpp_data['prompt'] = prompt
	koboldcpp_data['memory'] = generate_koboldcpp_memory_tag(character_data['data'], prompt, username)
	print(koboldcpp_data)

	async with aiohttp.ClientSession() as session:
		async with session.post(KOBOLDCPP_API_ENDPOINT, json=koboldcpp_data) as response:
			response_data = await response.json()  # Get JSON response
			print("Response:", response_data)
			return response_data['results'][0]['text']

	return ""


async def set_character(ctx: discord.ApplicationContext, new_character_data:TavernCardV2, username:str="User", alt_prompt:int = -1, optional_file_attachment:Union[str,None] = None):
	global message_history
	global character_data


	if len(new_character_data['data']['first_mes']) > 1950:
		await ctx.respond("❌ This character card's starting message is over 2000 characters. It can't be used with discord.", ephemeral=True)
	elif 'data' not in new_character_data:
		await ctx.respond("❌ This isn't a character card. Maybe you tried loading a lorebook by accident?", ephemeral=True)
	else:
		character_data = new_character_data
		first_message = character_data['data']['first_mes']
		if alt_prompt >= 0 and alt_prompt < len(character_data['data']["alternate_greetings"]):
			first_message = character_data['data']["alternate_greetings"][alt_prompt]

		message_history.clear()
		message_history.append(character_data['data']['name'] +": "+first_message)

		response = "-# ✅ The card was loaded succesfully. As with any other LLM, generation does not start until the first reply. Remember to tag the bot for it to read your message!"
		if 'character_book' in character_data['data'] and character_data['data']['character_book']:
			response += "\n-# ✅ A lorebook was loaded for this card: "+str(character_data['data']['character_book']["name"])

		if len(character_data['data']["alternate_greetings"]) > 0 and alt_prompt == -1:
			response += "\n-# ❇️ This card supports alternate starting prompts. If you would like an alternate prompt, use the alt_prompt option when selecting the character."
		response += "\n\n"+first_message.replace("{{char}}", character_data['data']['name']).replace("{{user}}",username)
		
		#Send to discord
		file = None
		if optional_file_attachment:
			file = discord.File(optional_file_attachment)
		await ctx.respond(response, file=file)
		nick_changed, err_message = await set_nickname(ctx, character_data['data']['name'])
		print("Loaded new character card! "+character_data['data']['name'])



async def set_nickname(ctx: discord.ApplicationContext, nickname: str) -> Tuple[bool, str]:
	"""
	A slash command that allows administrators to change the bot's nickname.

	Args:
		ctx (discord.ApplicationContext): The interaction context.
		nickname (str): The new nickname for the bot.
	"""
	if not ctx.guild:
		return False,"❌ Error: This command can only be used in a server."

	try:
		# Get the bot's member object in the guild
		bot_member = ctx.guild.get_member(bot.user.id)

		# Ensure bot member is found
		if bot_member is None:
			return False, "❌ Error: Unable to find bot in the server."

		# Change nickname
		await bot_member.edit(nick=nickname)
		
		print(f"Changed bot's nickname to: {nickname}")
		return True, f"✅ Bot's nickname successfully changed to **{nickname}**!"

	except discord.Forbidden:
		return False, "❌ Error: I don't have permission to change my nickname."
	except Exception as e:
		return False, f"❌ Error: An unexpected issue occurred ({str(e)})."
	#return False, "Unknown error. Shouldn't get this far."



# This is a function so it will update when using the slash command instead of needing to restart the bot
async def list_installed_characters(ctx: discord.AutocompleteContext) -> list:
	val = ctx.value.removesuffix(".json")
	return glob(f"*{val}*.json")

async def get_alternative_prompts(ctx: discord.AutocompleteContext) -> list:
	prompts = ["Default"]
	print(ctx.value)

	try:
		card = ctx.options["card"]
		with open(card,'r', encoding='utf-8') as f:
			character_data:TavernCardV2 = json.load(f)
			if 'data' in character_data:
				if len(character_data['data']['alternate_greetings']) > 0:
					for alt_prompt in character_data['data']['alternate_greetings']:
						prompts.append(alt_prompt[:100]) #Discord API does not allow more than 100 characters...
	except:
		pass

	#print(prompts)
	return prompts

def load_character_from_card_image(card_data: str | BytesIO | os.PathLike) -> TavernCardV2 | None:
	try:
		with Image.open(card_data) as img:
			if 'chara' in img.info:
				return json.loads(base64.b64decode(img.info['chara']))
	except ValueError as e:
		print(e)
		print("Corruption in card or improper bytes passed?")
	except Exception as e:
		print(e)
		return None
	#return None
		#else:
		#	await ctx.respond("❌ This image doesn't seem to have any character card data embedded.", ephemeral=True)
		#	return
	#raise Exception("Failed to decode this card!")


@bot.slash_command(
	name="character",
	description="Sets the bot to a character that's been installed by the bot owner.",
	default_member_permissions=discord.Permissions(administrator=True)
)
@discord.option(
	"card",
	description="Pick an installed character card.",
	#autocomplete=lambda ctx: glob("Characters"+os.path.sep+"*.json") + glob("Characters"+os.path.sep+"*.png")
	# autocomplete=lambda ctx: list(
	# 	filter(
	# 		lambda f: os.path.isfile(os.path.join("Characters", f)) and f.lower().endswith(('.png', '.json')),
	# 		os.listdir("Characters")
	# 	)
	# )
	autocomplete=lambda ctx: list([
        f for f in os.listdir("Characters")
        if os.path.isfile(os.path.join("Characters", f)) and f.lower().endswith(('.png', '.json'))
    ])
)
@discord.option(
	"alt_prompt",
	description="If the selected card supports alternative greetings you can select one.",
	#required=False,
	default="Default",
	#autocomplete=list_installed_characters,
	autocomplete=get_alternative_prompts
)
@discord.option(
	"lorebook",
	description="Use a lorebook with this character, if it doesn't come with one.",
	required=False,
	#default="None",
	#autocomplete=list_installed_characters,
	autocomplete=lambda ctx: glob("Lorebooks"+os.path.sep+"*.json")
	#autocomplete=lambda ctx: os.listdir("Lorebooks")
)
async def autocomplete_basic_example(
	ctx: discord.ApplicationContext,
	card: str,
	alt_prompt:str,
	lorebook:str
):
	"""
	This demonstrates using the discord.utils.basic_autocomplete helper function.

	For the `color` option, a callback is passed, where additional
	logic can be added to determine which values are returned.

	For the `animal` option, a static iterable is passed.

	While a small amount of values for `animal` are used in this example,
	iterables of any length can be passed to discord.utils.basic_autocomplete

	Note that the basic_autocomplete function itself will still only return a maximum of 25 items.
	"""
	card_img = None
	card = os.path.join("Characters",card)

	if card.lower().endswith("png"):
		card_img = card
		tmp_data = load_character_from_card_image(card)
		if tmp_data:
			character_data:TavernCardV2 = tmp_data
		else:
			await ctx.respond("❌ This image doesn't seem to have any character card data embedded.", ephemeral=True)
			return
	else:
		with open(card,'r', encoding='utf-8') as f:
			character_data:TavernCardV2 = json.load(f)

	if lorebook:
		try:
			with open(lorebook,'r', encoding='utf-8') as f_lorebook:
				lorebook_data:CharacterBook = json.load(f_lorebook)
				print("Loaded lorebook "+lorebook)
				if type(lorebook_data['entries'])==dict:
					lorebook_data['entries'] = list(lorebook_data['entries'].values())

				character_data['data']['character_book'] = lorebook_data
		except:
			pass


	alt_prompt_num:int = -1
	if alt_prompt != "Default":
		for i in range(len(character_data['data']['alternate_greetings'])):
			if character_data['data']['alternate_greetings'][i].startswith(alt_prompt):
				alt_prompt_num = i
				break
	await set_character(ctx, character_data, ctx.author.display_name, alt_prompt_num, card_img)


@bot.slash_command(
	name="upload",
	description="Sets the bot to the character card of your choosing",
	default_member_permissions=discord.Permissions(administrator=True)
)
@discord.option(
	"file", 
	description="The character card you want to upload. Must be PNG or JSON format.",
	required=True
)
async def upload(ctx: discord.ApplicationContext, file: discord.Attachment) -> None:
	"""
	Sets the bot to the character card of your choosing. Requires administrator permissions.

	Args:
		ctx (discord.ApplicationContext): The interaction context.
		file (discord.Attachment): The file attachment uploaded by the admin.
	"""
	global character_data
	card_img = None
	
	async def handle_file(file) -> Tuple[str, TavernCardV2 | None]:
		match os.path.splitext(file.filename.lower())[1]:
			case ".json":
				# Ensure file size is within limits (1024 KB)
				if file.size > 1024 * 1024:
					return "❌ Error: json file exceeds 1024 KB limit. This does not seem to be a valid character card.", None
				try:
					# Download and read the JSON file
					file_content:bytes = await file.read()
					return "", json.loads(file_content.decode("utf-8"))
				except json.JSONDecodeError:
					return "❌ Error: Invalid JSON format. Unable to parse the file.", None
						
				# Log the successful upload
				# print(f"Admin {ctx.author} uploaded a valid JSON file: {file.filename}")
			case ".png":
				if file.size > 1024 * 1024 * 8:
					return "❌ Error: Images should be under 8MB.", None
				card_img = BytesIO(await file.read())
				tmp_data = load_character_from_card_image(card_img)
				if tmp_data:
					return "", tmp_data
				else:
					return "❌ This image doesn't seem to have any character card data embedded.", None
			case _:
				return "❌ Not a valid file type. Only JSON and PNG is supported.", None
			
	error, new_data = await handle_file(file)
	if error:
		await ctx.respond(error, ephemeral=True)
		return

	await set_character(ctx, new_data, ctx.author.display_name, -1, card_img) #type: ignore


# @bot.slash_command(
# 	name="nickname",
# 	description="Change the bot's nickname (admin only)",
# 	default_member_permissions=discord.Permissions(administrator=True)
# )
# async def nickname(ctx: discord.ApplicationContext, nickname: str) -> None:
# 	"""
# 	A slash command that allows administrators to change the bot's nickname.

# 	Args:
# 		ctx (discord.ApplicationContext): The interaction context.
# 		nickname (str): The new nickname for the bot.
# 	"""
# 	nick_changed, err_message = await set_nickname(ctx, nickname)
# 	await ctx.respond(err_message, ephemeral=True)

@bot.slash_command(
	name="retry",
	description="Redo the last message this AI sent."
)
async def retry(ctx: discord.ApplicationContext) -> None:
	#nick_changed, err_message = await set_nickname(ctx, nickname)
	#await ctx.respond(err_message, ephemeral=True)
	if len(message_history) > 2:
		#print(message_history)
		message_history.pop()
		print("Pop last response, trying again!")
		#print(message_history)
	else:
		await ctx.respond("The character hasn't spoken yet. There's nothing to redo.", ephemeral=True)
		return
	new_message = await ctx.respond("(Pls wait... Character is speaking...)")

	resp = await contact_koboldcpp(message_history, character_data, ctx.author.display_name)
	if resp:
		await new_message.edit(content=resp)
		#The LLM will generate a space since it thinks it's generating the part after the :. So no need for a space here.
		#Also, replace the name back to {{user}} (Maybe we should just set a unique name and replace when passing to discord...)
		message_history.append(character_data['data']['name'].replace(ctx.author.display_name,"{{user}}")+":"+resp)
	else:
		await new_message.edit(content="LLM Error...? Got no response...")


@bot.event
async def on_message(message: discord.Message) -> None:
	"""
	Handles incoming messages.
	
	If the message mentions the bot, logs the message content
	without the bot’s mention and sends a reply.
	
	Args:
		message (discord.Message): The incoming message object.
	"""
	global character_data
	global message_history

	# Ignore messages sent by bots to prevent loops
	if message.author.bot:
		return

	# Check if the bot is mentioned in the message
	if bot.user in message.mentions:

		if not character_data:
			await message.reply("Hey, I don't have a character loaded yet! Use /upload so I can respond like a real human! Or if you would prefer, use /character to pick from a list of installed characters!")
			return

		# Remove all occurrences of the bot's mention from the message content.
		mention_str: str = bot.user.mention
		# It is possible that the message includes extra spaces and newlines,
		# so we clean it up by stripping.
		content_without_mention: str = message.content.replace(mention_str, "").strip()

		# Log the message in the console without the mention.
		print(f"Received message (without bot mention): {content_without_mention}")
		message_history.append("{{user}}: "+content_without_mention)
		#print(message_history)
		resp = await contact_koboldcpp(message_history, character_data, message.author.display_name)
		if resp:
			await message.reply(resp)
			#The LLM will generate a space since it thinks it's generating the part after the :. So no need for a space here.
			#Also, replace the name back to {{user}} (Maybe we should just set a unique name and replace when passing to discord...)
			message_history.append(character_data['data']['name'].replace(message.author.display_name,"{{user}}")+":"+resp)
		else:
			await message.reply("LLM Error...? Got no response...")


		# Reply to the message since the bot was mentioned.
		#await message.reply("You called me?")

	# Allow other command processing if needed.
	# await bot.process_commands(message)


@bot.event
async def on_ready() -> None:
	"""
	Event called when the bot is ready and connected.
	"""
	print(f"The bot is ready!")
	print(f'Logged in as {bot.user} (ID: {bot.user.id})')

if __name__ == '__main__':
	# Retrieve your Discord bot token from environment variable or replace with your token string.
	#TOKEN: str = os.getenv("DISCORD_TOKEN", "your_token_here")
	bot.run(TOKEN)
