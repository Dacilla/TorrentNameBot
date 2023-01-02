import requests
import argparse
import logging
import json
import os
import configparser
import sys
import re
import discord

from pprint import pprint
from datetime import datetime
from babel import Locale

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def main():
    parser = argparse.ArgumentParser(
        description="Script to take in a mediainfo JSON from pastebin and output a properly named torrent post"
    )
    parser.add_argument(
        "--link", action="store",
        help="Given mediainfo link containing mediainfo JSON",
        type=str
    )
    parser.add_argument(
        "--tmdb", action="store",
        help="TMDB ID",
        type=str
    )
    parser.add_argument(
        "--group", action="store",
        help="Group tag (e.g. NTb, SMURF, HONE)",
        type=str
    )
    parser.add_argument(
        "-m",
        "--movie",
        action="store_true",
        default=False,
        help="Enable if input is a movie"
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="debug mode", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s {version}".format(version=__VERSION),
    )

    arg = parser.parse_args()
    level = logging.INFO
    if arg.debug:
        level = logging.DEBUG

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=level)
    logging.info(f"Version {__VERSION} starting...")

    tmdb_api, bot_token = verify_settings()
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f'{client.user} has connected to Discord!')
        print(f'{client.user} is connected to the following guilds:\n')
        for guild in client.guilds:
            print(f'{guild.name}(id: {guild.id})\n')

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return

        if "!tv " in message.content.lower() or "!mo " in message.content.lower():
            givenText: str = message.content
            if "!tv" in message.content.lower():
                movie = False
            else:
                movie = True
            givenText = givenText.replace("!tv ", "")
            givenText = givenText.replace("!mo ", "")
            givenText = givenText.split(" ")
            if not len(givenText) == 3:
                response = "You have to give both a pastebin link and the TMDB ID"
                await message.reply(response, mention_author = True)
            else:
                link = givenText[0]
                tmdbID = givenText[1]
                group = givenText[2]
                result, mediainfo = checkContents(link)
                if not result:
                    response = "Your given link is not a valid pastebin link"
                    await message.reply(response, mention_author = True)
                else:
                    result, tmdbInfo = get_tmdb_info(tmdbID, tmdb_api, movie)
                    if not result:
                        response = "There was a failure when getting the info from TMDB. Please notify bot creator."
                        await message.reply(response, mention_author = True)
                    else:
                        postName = build_post_name(tmdbInfo, mediainfo, movie, group)
                        response = f"`{postName}`"
                        await message.reply(response, mention_author = True)

    client.run(bot_token)
    sys.exit()


def checkContents(link: str):
    if "pastebin" not in link:
        logging.error("No pastebin link found in input: " + link)
        return False
    elif "raw" not in link:
        link = link.replace(".com", ".com/raw")
    valid, text = is_valid_pastebin_link(link)
    if valid:
        try:
            jsonText = json.loads(text)
            pprint(jsonText)
            return True, jsonText
        except Exception as e:
            logging.error("Exception occured while processing JSON: " + e)
            return False
    else:
        logging.error(f"Invalid pastebin link given. Status code received: {text}. Link used {link}")
        return False


def build_post_name(tmdbData, mediaInfo, movie, group='NOGRP'):
    # Create torrent file name from TMDB and Mediainfo
    # Template:
    # TV: ShowName (Year) S00 (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
    # MOVIE: ShowName (Year) EDITION (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
    # pprint(mediaInfoText)
    if movie:
        showName: str = tmdbData['original_title']
    else:
        showName: str = tmdbData['name']
    showName = showName.replace(":", " -")
    logging.info("Name: " + str(showName))
    if movie:
        dateString = tmdbData['release_date']
    else:
        dateString = tmdbData['first_air_date']
    date = datetime.strptime(dateString, "%Y-%m-%d")
    year = str(date.year)
    logging.info("Year: " + year)
    file = os.path.basename(mediaInfo['media']['@ref'])
    if not movie:
        season = get_season(file)
        logging.info("Season: " + season)
    # Detect resolution
    # TODO: Detect whether it's progressive or interlaced
    acceptedResolutions = "2160p|1080p|720p"
    match = re.search(acceptedResolutions, file)
    if match:
        resolution = match.group()
    else:
        width = mediaInfo['media']['track'][1]['Width']
        height = mediaInfo['media']['track'][1]['Height']
        resolution = getResolution(width=width, height=height)
    if "Interlaced" in mediaInfo:
        resolution = resolution.replace("p", "i")
    logging.info("Resolution: " + resolution)
    colourSpace = get_colour_space(mediaInfo)
    logging.info("Colour Space: " + colourSpace)
    if 'HEVC' in mediaInfo['media']['track'][1]['Format']:
        if 'h265' in file.lower():
            videoCodec = 'H265'
        else:
            videoCodec = "x265"
    elif "VC-1" in mediaInfo['media']['track'][1]['Format']:
        videoCodec = "VC-1"
    else:
        videoCodec = "H264"
    logging.info("Video Codec: " + videoCodec)
    # Detect audio codec
    audio = get_audio_info(mediaInfo)
    logging.info("Audio: " + audio)
    # Get language
    language = get_language_name(mediaInfo['media']['track'][2]['Language'])
    logging.info("Language: " + language)
    # Get source
    # if arg.source:
    #     source = arg.source
    # else:
    #     source = ""
    # logging.info("Source: " + source)
    if group is None:
        group = "NOGRP"
    logging.info("Group: " + group)
    # Get Edition
    # if arg.edition:
    #     edition = " " + arg.edition
    # else:
    #     edition = ""
    # Get if repack
    if "REPACK" in file:
        repack = " [REPACK]"
    else:
        repack = ""
    # Construct torrent name
    if movie:
        postName = f"{showName} ({year}) ({resolution} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}"
    else:
        postName = f"{showName} ({year}) {season} ({resolution} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}"
    return postName


def get_colour_space(mediaInfo):
    if "HDR" not in mediaInfo:
        return "SDR"
    if "Dolby Vision" in mediaInfo['media']['track'][1]['HDR_Format']:
        if "HDR10" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
            return "DV HDR"
        else:
            return "DV"
    return "HDR"


def get_audio_info(mediaInfo):
    # Codec
    codecsDict = {
        "E-AC-3": "EAC3",
        "MLP FBA": "TrueHD",
        "DTS": "DTS",
        "AAC": "AAC",
        "PCM": "PCM",
        "AC-3": "DD"
    }
    audioFormat = None
    if 'Format_Commercial_IfAny' in str(mediaInfo):
        if mediaInfo['media']['track'][2]['Format_Commercial_IfAny']:
            commercialFormat = mediaInfo['media']['track'][2]['Format_Commercial_IfAny']
            if "Dolby Digital" in commercialFormat:
                if "Plus" in commercialFormat:
                    audioFormat = "DDP"
                else:
                    audioFormat = "DD"
            elif "TrueHD" in commercialFormat:
                audioFormat = "TrueHD"
            elif "DTS" in commercialFormat:
                if "HD High Resolution" in commercialFormat:
                    audioFormat = "DTS-HD HR"
                elif "Master Audio" in commercialFormat:
                    audioFormat = "DTS-HD MA"

    if audioFormat is None:
        if mediaInfo['media']['track'][2]['Format'] in codecsDict:
            audioFormat = codecsDict[mediaInfo['media']['track'][2]['Format']]

    if audioFormat is None:
        logging.error("Audio format was not found")
    # Channels
    channelsNum = mediaInfo['media']['track'][2]['Channels']
    channelsLayout = mediaInfo['media']['track'][2]['ChannelLayout']
    if "LFE" in channelsLayout:
        channelsNum = str(int(channelsNum) - 1)
        channelsNum2 = ".1"
    else:
        channelsNum2 = ".0"
    channelsNum = channelsNum + channelsNum2
    audioInfo = audioFormat + " " + channelsNum
    return audioInfo


def get_language_name(language_code):
    try:
        # Create a Locale instance with the given language code
        locale = Locale(language_code)
        # Return the language name in the locale's native language
        return locale.get_language_name(locale.language)
    except Exception:
        # If the language code is invalid or the name cannot be determined, return an empty string
        return ''


def getResolution(width, height):
    width_to_height_dict = {"720": "576", "960": "540", "1280": "720", "1920": "1080", "4096": "2160", "3840": "2160", "692": "480", "1024": "576"}

    if width in width_to_height_dict:
        height = width_to_height_dict[width]
        return f"{str(height)}p"

    if height is not None:
        return f"{str(height)}p"

    return input("Resolution could not be found. Please input the resolution manually (e.g. 1080p, 2160p, 720p)\n")


def get_season(filename):
    # Use a regex to match the season string
    match = re.search(r'S\d\d', filename)
    if match:
        # If a match is found, return the season string
        return match.group(0)
    else:
        # If no match is found, return an empty string
        return ''


def verify_settings():
    if not os.path.exists('settings.ini'):
        logging.info("No settings.ini file found. Generating...")
        config = configparser.ConfigParser()

        config['DEFAULT'] = {
            'TMDB_API': '',
            'BOT_TOKEN': ''
        }

        with open('settings.ini', 'w') as configfile:
            config.write(configfile)

        sys.exit("settings.ini file generated. Please fill out before running again")

    # Load the INI file
    config = configparser.ConfigParser()
    config.read('settings.ini')
    tmdb_api = config['DEFAULT']['TMDB_API']
    bot_token = config['DEFAULT']['BOT_TOKEN']
    return tmdb_api, bot_token


def get_tmdb_info(TMDB_ID, tmdb_api, movie: bool):
    if tmdb_api == "":
        logging.error("TMDB_API field not filled in settings.ini")
        sys.exit()
    # Get TMDB info
    logging.info("Getting TMDB description")

    # Build the URL for the API request
    if movie:
        url = f'https://api.themoviedb.org/3/movie/{TMDB_ID}?api_key={tmdb_api}'
    else:
        url = f'https://api.themoviedb.org/3/tv/{TMDB_ID}?api_key={tmdb_api}'

    # Make the GET request to the TMDb API
    response = requests.get(url)
    if response.status_code == 200:
        # Get the JSON data from the response
        tmdbData = response.json()
        # Print the description of the TV show
        logging.debug("description gotten: " + tmdbData['overview'])
        return True, tmdbData
    else:
        logging.error("Error when getting info from TMDB API")
        pprint(response.json())
        return False


def is_valid_pastebin_link(link):
    # Send a request to the link
    response = requests.get(link)

    # If the response code is 200, return True
    if response.status_code == 200:
        return True, response.text

    # Otherwise, return False
    return False, response.status_code


if __name__ == "__main__":
    main()
