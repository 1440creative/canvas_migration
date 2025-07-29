import os
import time
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv() #load .env file

class CanvasAPI:
    def __init__(self, base_url, token):
        self.base_url = base_url if base_url.endswith('/') else base_url + '/'
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })
        
    def get(self, endpoint, params=None):
        """Get request with pagination support"""
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        results = []
        while url:
            r = self.session.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                return data #single obj, no pagination
            # look for pagination link header
            url = None
            if 'link' in r.headers:
                for link in r.headers['link'].split(','):
                    if 'rel="next"' in link:
                        url = link[link.link.find('<')+1:link.find('>')]
                        break
        return results
                