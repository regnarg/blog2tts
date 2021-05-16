#!/usr/bin/python3

import sys, os, re, json
import subprocess
import trafilatura
import requests
import bs4
from bs4 import BeautifulSoup
from slugify import slugify
from xml.etree import ElementTree

UA = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'
HDRS = {'User-Agent': UA}

cfg = json.loads(open(os.path.join(os.path.dirname(__file__), 'config.json')).read())

def tts_voicerss(text):
    VOICERSS_API_KEY = open(os.path.join(os.path.dirname(__file__), 'voicerss_api_key.txt')).read().strip()
    params = {
        'key': VOICERSS_API_KEY,
        'hl': 'en-us',
        'v': 'Mary', # seems most tolerable
        'src': text,
        'r': '0',
        'c': 'mp3',
        'f': '44khz_16bit_stereo',
        'ssml': 'false',
        'b64': 'false'
    }
    resp = requests.post('https://api.voicerss.org/', data=params)
    print(resp.status_code)
    print(len(resp.content))
    if resp.status_code == 200:
        return resp.content
    else:
        raise Exception(resp.text)

def tts_azure_single(text, *, format='audio-24khz-160kbitrate-mono-mp3'):
    #from azure.cognitiveservices.speech import AudioDataStream, SpeechConfig, SpeechSynthesizer, SpeechSynthesisOutputFormat
    #from azure.cognitiveservices.speech.audio import AudioOutputConfig
    #speech_config = SpeechConfig(subscription=cfg['azure_key'], region=cfg['azure_region'])
    base_url = 'https://%s.tts.speech.microsoft.com/'%cfg['azure_region']
    path = 'cognitiveservices/v1'
    constructed_url = base_url + path
    headers = {
        #'Authorization': 'Bearer ' + cfg['azure_key'],
        'Ocp-Apim-Subscription-Key': cfg['azure_key'],
        'Content-Type': 'application/ssml+xml',
        'X-Microsoft-OutputFormat': format,
        'User-Agent': 'rgtts0'
    }
    xml_body = ElementTree.Element('speak', version='1.0')
    xml_body.set('{http://www.w3.org/XML/1998/namespace}lang', 'en-us')
    voice = ElementTree.SubElement(xml_body, 'voice')
    voice.set('{http://www.w3.org/XML/1998/namespace}lang', 'en-US')
    voice.set('name', os.environ.get('AZURE_VOICE', cfg['azure_voice'])) # Short name for 'Microsoft Server Speech Text to Speech Voice (en-US, Guy24KRUS)'
    voice.text = text
    body = ElementTree.tostring(xml_body)

    response = requests.post(constructed_url, headers=headers, data=body)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(response.text)



def split_chunks(body, max_size):
    cur_chunk = []
    chunks = []
    chunk_size = 0
    for line in body.splitlines():
        new_size = chunk_size + len(line)
        if new_size > max_size:
            chunks.append('\n'.join(cur_chunk))
            cur_chunk = []
            chunk_size = 0
        else:
            cur_chunk.append(line)
            chunk_size += len(line)
    if cur_chunk:
        chunks.append('\n'.join(cur_chunk))
    return chunks

# Azure is limited to 10min output. Emerically, this seems to be around 8000 chars,
# using 5000 to be safe.
AZURE_CHUNK_SIZE = 5000
def tts_azure_chunked(body):
    chunks = split_chunks(body, AZURE_CHUNK_SIZE)
    print("Split into",len(chunks),"chunks")
    chunk_data = []
    for chunk in chunks:
        r = tts_azure_single(chunk, format='raw-16khz-16bit-mono-pcm')
        chunk_data.append(r)
    data = b''.join(chunk_data)
    print(len(data))
    mp3_data = subprocess.run(
            ['ffmpeg',  '-f', 's16le', '-ar', '16k', '-ac', '1',
                '-i', '-', '-acodec', 'mp3', '-f', 'mp3', '-b:a', '160k', '-'],
            input=data, stdout=subprocess.PIPE).stdout
    return mp3_data

def tts_azure(body):
    if len(body) > AZURE_CHUNK_SIZE:
        return tts_azure_chunked(body)
    else:
        return tts_azure_single(body)

TTS_ENGINES = dict(azure=tts_azure, voicerss=tts_voicerss)

def tts(*a, **kw):
    return TTS_ENGINES[cfg['tts']](*a, **kw)



def extract_body(url):
    #html = trafilatura.fetch_url(url)
    html = requests.get(url, headers=HDRS).text
    text = trafilatura.extract(html, include_comments=False)
    soup = BeautifulSoup(html, features="lxml")
    title = soup.title.string.split(' - ')[0] # try to strip away website name
    text = title + '.\n\n' + (text or '') # say the title at the beginning
    return title, text

def process(url, *, filename_prefix='', out_dir='.'):
    if url.startswith('#'): return
    title, body = extract_body(url)
    print("Processing", title, url)
    fn = os.path.join(out_dir, filename_prefix + slugify(title) + '.mp3')
    transcript_fn = os.path.join(out_dir, filename_prefix + slugify(title) + '.txt')
    with open(transcript_fn, 'w') as fh:
        fh.write(body)
    if os.path.exists(fn):
        print(fn, "already exists, skipping")
        return
    r = tts(body)
    with open(fn, 'wb') as fh:
        fh.write(r)


def process_list(urls, *, out_dir='.'):
    urls = expand_list(urls)
    for idx, url in enumerate(urls):
        process(url, out_dir=out_dir, filename_prefix='%03d-' % (idx+1))

#
def expand_lw_sequence(seq_url):
    """
    @param seq_url: sequence url, i.e. https://www.lesswrong.com/s/<something>
    """
    # FRAGILE, TODO use API
    html = requests.get(seq_url).text
    b = bs4.BeautifulSoup(html, features="lxml")
    urls = [ 'https://lesswrong.com' + x['href'] for x in b.select('.ChaptersItem-posts  .PostsItem2-postsItem .PostsTitle-root a') if x['href'].startswith('/s/') ]
    # Include the sequence page, which contains the introduction to the sequence.
    # It seems that trfilatura is able to strip the links to individual posts so that
    # only the intro remains in the audio.
    return [seq_url] + urls

LW_SEQUENCE_RE = re.compile(r'^https://www.lesswrong.com/s/[^/]+$')

def expand_list(urls):
    r = []
    for url in urls:
        if LW_SEQUENCE_RE.match(url): # LW sequence
            r += expand_lw_sequence(url)
        else:
            r.append(url)
    return r

if __name__ == '__main__':
    process_list(sys.stdin.read().strip().splitlines())

