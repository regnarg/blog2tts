#!/usr/bin/python3

import sys, os, re
import trafilatura
import requests
from bs4 import BeautifulSoup
from slugify import slugify

UA = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'
HDRS = {'User-Agent': UA}

VOICERSS_API_KEY = open(os.path.join(os.path.dirname(__file__), 'voicerss_api_key.txt')).read().strip()

def tts(text):
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

def extract_body(url):
    #html = trafilatura.fetch_url(url)
    html = requests.get(url, headers=HDRS).text
    text = trafilatura.extract(html, include_comments=False)
    soup = BeautifulSoup(html, features="lxml")
    title = soup.title.string.split(' - ')[0] # try to strip away website name
    text = title + '.\n\n' + text # say the title at the beginning
    return title, text

def process(url, *, filename_prefix='', out_dir='.'):
    title, body = extract_body(url)
    print("Processing", title, url)
    fn = os.path.join(out_dir, filename_prefix + slugify(title) + '.mp3')
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

