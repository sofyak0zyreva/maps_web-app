import requests
from flask import Flask, render_template, session, jsonify, request
from fastkml import kml
import gpxpy
import time
import os
import geojson
from flask_cors import CORS
import xml.etree.ElementTree as ET
from flask_caching import Cache

app = Flask(__name__)
# Configure caching
cache = Cache(app, config={'CACHE_TYPE': 'simple'})
# Configure CORS to allow the front-end origin
CORS(app, resources={r"/api/*": {"origins": "http://127.0.0.1:5500"}})

# Set a secret key for the session
app.secret_key = os.urandom(24)

# Authentication URL (the endpoint you use to get the token)
AUTH_URL = "http://176.74.9.162:3318/VegaPlusST07/api/auth"

# API URL (the endpoint you will query using the token)
API_URL = "http://176.74.9.162:3318/VegaPlusST07/api/getDataTable"

login = os.getenv('LOGIN')
password = os.getenv('PASSWORD')

# Function to get a new bearer token
def get_new_token():
	# Data payload for the request (same as the --data in the curl command)
	auth_data = {
		'login': login,
		'password': password
	}
	# Headers (same as --header in the curl command)
	headers = {
		'Content-Type': 'application/x-www-form-urlencoded'
	}
	auth_response = requests.post(AUTH_URL, data=auth_data, headers=headers)
	# Check if the response is successful
	if auth_response.status_code == 200:
		#token = "Bearer " + auth_response.json().get('accessToken')
		token = auth_response.json().get('accessToken')

		session['token'] = token
		session['token_time'] = time.time() 
		#print(token)
		return token
	else:
		return None
		
# Function to check if token is still valid (within 24 hours)
def get_valid_token():
	if 'token' in session and 'token_time' in session:
		token_age = time.time() - session['token_time']
		if token_age < 24*60*60:

			return session['token']
	return get_new_token()

routes = os.getenv('ROUTES')
regions = os.getenv('REGIONS')

@app.route('/api/getDataTable', methods=['GET', 'POST'])
@cache.cached(timeout=90)  # Cache JSON data for 90 seconds
def get_data():
	table_name = request.args.get('type')  # Get 'type' parameter from the URL
	#print("Query Parameters:", request.args)
	#print(table_name)
	if table_name == 'routes':
		table_name = routes  # Fetch routes
	elif table_name == 'regions':
		table_name = regions # Fetch regions
	token = get_valid_token()
	if token is None:
		return jsonify({"error": "Unable to authenticate and retrieve token"}), 500

	headers = {"Authorization": f"Bearer {token}"}
	data_payload = {"tablename": table_name, "limit": 0}

	#print(data_payload)
	api_response = requests.post(API_URL, data=data_payload, headers=headers)
	print(f"API Response Status Code: {api_response.status_code}")
	print(f"API Response Content: {api_response.text}")
	if table_name == routes:  update_geojson(api_response.json())
	if api_response.status_code == 200:
		return api_response.json()
	return jsonify({"error": "Failed to fetch routes"}), 500

geojson_file_path = './routes.geojson'

def update_geojson(routes_data):
	if os.path.exists(geojson_file_path):
		with open(geojson_file_path, 'r', encoding='utf-8') as f:
			existing_geojson = geojson.load(f)
			#print(existing_geojson)
			existing_route_ids = {feature['properties']['id'] for feature in existing_geojson['features']}
			print(existing_route_ids)
	else:
		existing_geojson = geojson.FeatureCollection([])
		existing_route_ids = set()

	new_features = []
	for route in routes_data:
		route_id = route.get('trail_2408')
		name = route.get('name')
		if route_id not in existing_route_ids:
			print(route_id)
			print(f"Processing new route: {name}")
			url = route.get('gps_track')
			properties = {"name": name, "id": route_id}
			if url:
				geojson_data = process_file(url, properties)
				print(geojson_data)
				if geojson_data:
					existing_geojson['features'].extend(geojson_data['features'])

	with open('routes.geojson', 'w', encoding='utf-8') as f:
		geojson.dump(existing_geojson, f)
	print(f"GeoJSON file updated with {len(new_features)} new routes.")

def get_geojson(routes_data):
	geojson_routes = {
			"type": "FeatureCollection",
			"features": []
		}
	for route in routes_data:
		url = route.get('gps_track')
		properties = {"name": route.get('name'), "id": route.get('trail_2408')}
		print(url)
		if url != None: 
			geojson_data = process_file(url, properties)
			#print(geojson_data)
			if geojson_data != None:
				geojson_routes['features'].extend(geojson_data['features'])
	
	print(geojson_routes)
	with open('route4.geojson', 'w', encoding='utf-8') as geojson_file:
		geojson.dump(geojson_routes, geojson_file)
	print("GeoJSON file saved as route4.geojson")

def process_file(url, route_properties):
	response = requests.get(url)
	if response.status_code != 200:
		raise Exception(f"Failed to download file: {response.status_code}")
	content = response.content.decode('utf-8', errors='ignore')
	if "<gpx" in content:
		return convert_gpx_to_geojson(response.content, route_properties)
	elif "<kml" in content:
		return convert_kml_to_geojson(response.content, route_properties)

def convert_gpx_to_geojson(gpx_content, route_properties):
	gpx = gpxpy.parse(gpx_content.decode('utf-8'))
	features = []
	for track in gpx.tracks:
		for segment in track.segments:
			coordinates = [[point.longitude, point.latitude] for point in segment.points]
			geometry = geojson.LineString(coordinates)
			features.append(geojson.Feature(geometry=geometry, properties=route_properties))
	feature_collection = geojson.FeatureCollection(features)
	return feature_collection

def convert_kml_to_geojson(kml_content, route_properties):
	root = ET.fromstring(kml_content)
	features = []

	ns = {
		'kml': 'http://www.opengis.net/kml/2.2',
		'gx': 'http://www.google.com/kml/ext/2.2'
	}
	coords = root.findall('.//gx:Track/gx:coord', namespaces=ns)
	coordinates = []
	for coord in coords:
		lon, lat, alt = map(float, coord.text.split())
		coordinates.append([lon, lat, alt])

	if coordinates != []:
		geometry = geojson.LineString(coordinates)
		features.append(geojson.Feature(geometry=geometry, properties=route_properties))
		feature_collection = geojson.FeatureCollection(features)
		return feature_collection
	
	ns = {'kml': 'http://www.opengis.net/kml/2.2'}
	for placemark in root.findall('.//kml:Placemark', ns):
		line_string = placemark.find('.//kml:LineString/kml:coordinates', ns)
		if line_string is not None:
			coords = line_string.text.strip().split()
			points = []
			for coord in coords:
				parts = list(map(float, coord.split(',')))
				if len(parts) >= 2: 
					lon, lat = parts[0], parts[1]  
					points.append((lon, lat))  
			geometry = geojson.LineString(points)
			features.append(geojson.Feature(geometry=geometry, properties=route_properties))

	feature_collection = geojson.FeatureCollection(features)
	return feature_collection

if __name__ == '__main__':
	app.run(port=5000, debug=True)

@app.route('/')
def home():
	return render_template('index.html')
