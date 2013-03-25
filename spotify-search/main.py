#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import jinja2
import os
from google.appengine.ext.webapp import template
import webapp2

from google.appengine.ext.webapp import util
from google.appengine.api import urlfetch
from google.appengine.api import memcache
import time
import logging

import xml.etree.cElementTree as etree
from cStringIO import StringIO
import urllib

import filters

jinja_environment = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))
jinja_environment.filters['truncate'] = filters.truncate

class MainHandler(webapp2.RequestHandler):
	
	def __init__(self, request=None, response=None):
		self.spotify = SearchService()
		self.initialize(request, response)
		
	def get(self):
		q = self.request.get('q')
		if q is None:
			return
		
		type = self.request.get('type')
		if type not in ['track', 'artist', 'album'] :
			type = 'track'
		
		t0 = time.clock()
		results = None
		error = None
		try:
			results = self.search(q, type)
		except Exception, e:
			logging.error(e)
			error = True
		dt = int((time.clock() - t0)*1000)
		
		template_values = {'query_time': dt, 'q': q, 'error':error, 'type':type, 'results': results }
		template = jinja_environment.get_template('index.html')
		self.response.out.write(template.render(template_values))	
	
	def search(self, terms, type):
		key = type + ':' + terms.strip().lower()
		results = memcache.get(key)
		if results is not None:
			return results
			
		results = self.spotify.search(type, terms)			
		if not memcache.add(key, results, 86400):
			logging.error("Failed to add %s results to memcache" % (key))
		return results
		

class ServiceException(Exception):
	def __init__(self, value):
		self.parameter = value
	
	def __str__(self):
		return repr(self.parameter)
		
class SearchResult(object):

	def __init__(self, search_terms, total_results, start_index, items_per_page, items):
		self.search_terms = search_terms
		self.total_results = total_results
		self.start_index = start_index
		self.items_per_page = items_per_page
		self.items = items
	
	def __str__(self):
		return "%s %s (%s)" % (self.search_terms, self.total_results, ', '.join([str(x) for x in self.items]))


class Track(object):
	
	def __init__(self, name, href, artist_name, artist_href, album_name, album_href, duration, popularity):
		self.name = name
		self.href = href
		self.artist_name = artist_name
		self.artist_href = artist_href
		self.duration = duration
		self.popularity = popularity
		self.album_name = album_name
		self.album_href = album_href
	
	def duration_str(self):
		minutes = int(self.duration/60)
		seconds = self.duration - minutes*60
		return "%d:%02d" % (minutes, seconds)
		
	def __str__(self):
		return "%s - %s" % (self.name, self.artist_name)

class Artist(object):
	def __init__(self, name, href, popularity):
		self.name = name
		self.href = href
		self.popularity = popularity
		
	def __str__(self):
		return "%s - %s" % (self.name, self.href)

class Album(object):
	def __init__(self, name, href, artist_name, artist_href, popularity, released, published):
		self.name = name
		self.href = href
		self.artist_name = artist_name
		self.artist_href = artist_href		
		self.popularity = popularity
		self.released = released
		self.published = published
		
	def __str__(self):
		return "%s - %s" % (self.name, self.href)
		
class SearchService(object):
	
	def search(self, type, term):
		encoded_term = urllib.quote(term.encode('utf-8'))
		url = 'http://ws.spotify.com/search/1/' + type + '?q=' + encoded_term
		result = urlfetch.fetch(url)
		if result.status_code != 200:
			logging.error("Spotify API failed to reply to query '%s': %s" % (url, result.result.status_code))
			raise ServiceException('Spotify API failed to reply to query')
		if type == 'track':
			return self.parse_track(result.content)
		elif type == 'artist':
			return self.parse_artist(result.content)
		elif type == 'album':
			return self.parse_album(result.content)
		else:
			raise ServiceException('Invalid type parameter: ' + type)
		
	def parse_track(self, data):
		search_terms = None
		total_results = None
		start_index = None
		items_per_page = None
		items = []
		# Awesome use of the namespace here... lovely to read...
		for event, elem in etree.iterparse(StringIO(data)):
			if (elem.tag == '{http://www.spotify.com/ns/music/1}track'):
				name = elem.findtext('{http://www.spotify.com/ns/music/1}name')
				href = elem.get('href')
				artist_name = elem.findtext('{http://www.spotify.com/ns/music/1}artist/{http://www.spotify.com/ns/music/1}name')
				artist_href = elem.find('{http://www.spotify.com/ns/music/1}artist/').get('href')
				album_name = elem.findtext('{http://www.spotify.com/ns/music/1}album/{http://www.spotify.com/ns/music/1}name')
				album_href = elem.find('{http://www.spotify.com/ns/music/1}album/').get('href')
				duration = int(float(elem.findtext('{http://www.spotify.com/ns/music/1}length')))
				popularity = int(float(elem.findtext('{http://www.spotify.com/ns/music/1}popularity'))*100)
				items.append(Track(name, href, artist_name, artist_href, album_name, album_href, duration, popularity))
				elem.clear()
			elif (elem.tag == '{http://www.spotify.com/ns/music/1}tracks'):
				search_terms = elem.find('{http://a9.com/-/spec/opensearch/1.1/}Query').get('searchTerms')
				total_results = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
				start_index = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}startIndex')
				items_per_page = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}itemsPerPage')
		return SearchResult(search_terms, total_results, start_index, items_per_page, items)
	
	def parse_artist(self, data):
		search_terms = None
		total_results = None
		start_index = None
		items_per_page = None
		items = []
		for event, elem in etree.iterparse(StringIO(data)):
			if (elem.tag == '{http://www.spotify.com/ns/music/1}artist'):
				name = elem.findtext('{http://www.spotify.com/ns/music/1}name')
				href = elem.get('href')
				popularity = int(float(elem.findtext('{http://www.spotify.com/ns/music/1}popularity'))*100)
				items.append(Artist(name, href, popularity))
				elem.clear()
			elif (elem.tag == '{http://www.spotify.com/ns/music/1}artists'):
				search_terms = elem.find('{http://a9.com/-/spec/opensearch/1.1/}Query').get('searchTerms')
				total_results = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
				start_index = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}startIndex')
				items_per_page = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}itemsPerPage')
		return SearchResult(search_terms, total_results, start_index, items_per_page, items)

	def parse_album(self, data):
		search_terms = None
		total_results = None
		start_index = None
		items_per_page = None
		items = []
		for event, elem in etree.iterparse(StringIO(data)):
			if (elem.tag == '{http://www.spotify.com/ns/music/1}album'):
				name = elem.findtext('{http://www.spotify.com/ns/music/1}name')
				href = elem.get('href')
				popularity = int(float(elem.findtext('{http://www.spotify.com/ns/music/1}popularity'))*100)
				artist_name = elem.findtext('{http://www.spotify.com/ns/music/1}artist/{http://www.spotify.com/ns/music/1}name')
				artist_href = elem.find('{http://www.spotify.com/ns/music/1}artist/').get('href')
				released = elem.findtext('{http://www.spotify.com/ns/music/1}released')
				published = elem.findtext('{http://www.spotify.com/ns/music/1}published')
				items.append(Album(name, href, artist_name, artist_href, popularity, released, published))
				elem.clear()
			elif (elem.tag == '{http://www.spotify.com/ns/music/1}albums'):
				search_terms = elem.find('{http://a9.com/-/spec/opensearch/1.1/}Query').get('searchTerms')
				total_results = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
				start_index = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}startIndex')
				items_per_page = elem.findtext('{http://a9.com/-/spec/opensearch/1.1/}itemsPerPage')
		return SearchResult(search_terms, total_results, start_index, items_per_page, items)


app = webapp2.WSGIApplication([('/', MainHandler)], debug=True)
