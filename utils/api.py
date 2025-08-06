import os
import time
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv
from typing import Dict, Any, Optional, Union, List

load_dotenv() #load .env file

class CanvasAPI:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url if base_url.endswith('/') else base_url + '/'
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })
        
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get request with pagination support"""
        # Remove leading slashes from endpoint to avoid urljoin dropping base path
        clean_endpoint = endpoint.lstrip("/")
        url = urljoin(self.base_url, clean_endpoint)
        #url = urljoin(self.base_url, endpoint.lstrip('/'))
        results: List[Dict[str, Any]] = []
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
                        url = link[link.find('<')+1:link.find('>')]
                        break
        return results
    
    def post(
        self, 
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None, 
        files: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        r = self.session.post(url, json=payload, files=files)
        r.raise_for_status()
        return r.json()
    
    def put(
        self, 
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        r = self.session.put(url, json=payload)
        r.raise_for_status()
        return r.json()
    
    def delete(self, endpoint: str) -> Optional[Dict[str, Any]]:
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        r = self.session.delete(url)
        r.raise_for_status()
        return r.json() if r.text else None
    
# instatiate two API clients (on-premise, cloud)
source_api = CanvasAPI(
    os.getenv("CANVAS_SOURCE_URL"),
    os.getenv("CANVAS_SOURCE_TOKEN")
)

target_api = CanvasAPI(
    os.getenv("CANVAS_TARGET_URL"),
    os.getenv("CANVAS_TARGET_TOKEN")
)
                