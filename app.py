import requests
from flask import Flask, render_template, session, jsonify, request
import gpxpy
import time
import os
import geojson
import xml.etree.ElementTree as ET
from flask_caching import Cache

app = Flask(__name__, instance_relative_config=True)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Set a secret key for the session
app.secret_key = os.urandom(24)

# Authentication URL (the endpoint to get the token)
AUTH_URL = "http://176.74.9.162:3318/VegaPlusST07/api/auth"

# API URL (the endpoint queried using the token)
API_URL = "http://176.74.9.162:3318/VegaPlusST07/api/getDataTable"

login = os.getenv('LOGIN')
password = os.getenv('PASSWORD')


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
        token = auth_response.json().get('accessToken')
        session['token'] = token
        session['token_time'] = time.time()
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
equipment = os.getenv('EQUIPMENT')
objects = os.getenv('REGOBJ')


@app.route('/api/getDataTable', methods=['GET', 'POST'])
@cache.cached(timeout=90, key_prefix=lambda: f"get_data_{request.args.get('type')}")
def get_data():
    query_param = request.args.get('type')
    table_mapping = {
        'routes': routes,
        'regions': regions,
        'equipment': equipment,
        'objects': objects
    }
    table_name = table_mapping.get(query_param)
    if not table_name:
        return jsonify({"error": "Invalid type parameter"}), 400

    token = get_valid_token()
    if token is None:
        return jsonify({"error": "Unable to authenticate and retrieve token"}), 500

    headers = {"Authorization": f"Bearer {token}"}
    data_payload = {"tablename": table_name, "limit": 0}
    api_response = requests.post(API_URL, data=data_payload, headers=headers)

    if api_response.status_code == 200:
        response_data = api_response.json()

        # Update data based on query_param
        update_mapping = {
            'routes': update_routes,
            'regions': update_regions,
            'equipment': update_equipment,
            'objects': update_objects
        }
        update_function = update_mapping.get(query_param)
        if update_function:
            update_function(response_data)

        return jsonify(response_data)  # Cache this response
    return jsonify({"error": "Failed to fetch routes"}), 500


routes_cache = None


def load_routes():
    global routes_cache
    geojson_file_path = os.path.join(app.instance_path, 'routes.geojson')
    if os.path.exists(geojson_file_path):
        with open(geojson_file_path) as f:
            routes_cache = geojson.load(f)


def update_routes(routes_data):
    geojson_routes_path = os.path.join(app.instance_path, 'routes.geojson')
    if os.path.exists(geojson_routes_path):
        with open(geojson_routes_path, 'r', encoding='utf-8') as f:
            existing_geojson = geojson.load(f)
            existing_route_ids = {feature['properties']['id']
                                  for feature in existing_geojson['features']}
    else:
        existing_geojson = geojson.FeatureCollection([])
        existing_route_ids = set()
    for route in routes_data:
        route_id = route.get('id')
        name = route.get('name')
        if route_id not in existing_route_ids:
            url = route.get('gps_track')
            properties = {"name": name, "id": route_id}
            if url:
                geojson_data = process_file(url, properties)
                existing_route_ids.add(route_id)
                if geojson_data:
                    existing_geojson['features'].extend(
                        geojson_data['features'])
    with open(geojson_routes_path, 'w', encoding='utf-8') as f:
        geojson.dump(existing_geojson, f)

# Add functions to enable access to geojson files from frontend


@app.route('/routes-geodata')
def routes_data():
    return jsonify(routes_cache)


regions_cache = None


def load_regions():
    global regions_cache
    geojson_file_path = os.path.join(app.instance_path, 'regions.geojson')
    if os.path.exists(geojson_file_path):
        with open(geojson_file_path) as f:
            regions_cache = geojson.load(f)


def update_regions(regions_data):
    geojson_regions_path = os.path.join(app.instance_path, 'regions.geojson')
    if os.path.exists(geojson_regions_path):
        with open(geojson_regions_path, 'r', encoding='utf-8') as f:
            existing_geojson = geojson.load(f)
            existing_regions_ids = {feature['properties']['link']
                                    for feature in existing_geojson['features']}
    else:
        existing_geojson = geojson.FeatureCollection([])
        existing_regions_ids = set()
    region_id = 1
    for region in regions_data:
        url = region.get('route_area_map')
        if url not in existing_regions_ids:
            if url:
                properties = {"link": url, "id": region_id}
                region_id += 1
                geojson_data = process_regions(url, properties)
                existing_regions_ids.add(url)
                if geojson_data:
                    existing_geojson['features'].extend(
                        geojson_data['features'])
    with open(geojson_regions_path, 'w', encoding='utf-8') as f:
        geojson.dump(existing_geojson, f)


@app.route('/regions-geodata')
def regions_data():
    return jsonify(regions_cache)


equipment_cache = None


def load_equipment():
    global equipment_cache
    geojson_file_path = os.path.join(app.instance_path, 'equipment.geojson')
    if os.path.exists(geojson_file_path):
        with open(geojson_file_path) as f:
            equipment_cache = geojson.load(f)


def update_equipment(equip_data):
    geojson_equip_path = os.path.join(app.instance_path, 'equipment.geojson')
    if os.path.exists(geojson_equip_path):
        with open(geojson_equip_path, 'r', encoding='utf-8') as f:
            existing_geojson = geojson.load(f)
            existing_equp_ids = {feature['properties']['id']
                                 for feature in existing_geojson['features']}
    else:
        existing_geojson = geojson.FeatureCollection([])
        existing_equp_ids = set()
    features = []
    for equip in equip_data:
        name = equip.get('device')
        ident = equip.get('id')
        type = equip.get('device_type')
        link_to_route = equip.get('ecotrails_passports_2418_id_2')
        longitude = equip.get('longitude')
        latitude = equip.get('latitude')
        try:
            longitude = float(longitude)
            latitude = float(latitude)
        except (TypeError, ValueError):
            continue  # Skip if coordinates are invalid
        if ident not in existing_equp_ids:
            if ident > 1:  # TODO: remove when db is fixed
                geometry = geojson.Point((longitude, latitude))
                features.append(geojson.Feature(geometry=geometry, properties={
                                "name": name, "id": ident, "type": type, "link_to_route": link_to_route}))
                existing_equp_ids.add(ident)
    geojson_data = geojson.FeatureCollection(features)
    if geojson_data:
        existing_geojson['features'].extend(geojson_data['features'])
    with open(geojson_equip_path, 'w', encoding='utf-8') as f:
        geojson.dump(existing_geojson, f)


@app.route('/equipment-geodata')
def equipment_data():
    return jsonify(equipment_cache)


objects_cache = None


def load_objects():
    global objects_cache
    geojson_file_path = os.path.join(app.instance_path, 'objects.geojson')
    if os.path.exists(geojson_file_path):
        with open(geojson_file_path) as f:
            objects_cache = geojson.load(f)


def update_objects(objects_data):
    geojson_objects_path = os.path.join(app.instance_path, 'objects.geojson')
    if os.path.exists(geojson_objects_path):
        with open(geojson_objects_path, 'r', encoding='utf-8') as f:
            existing_geojson = geojson.load(f)
            existing_objects_ids = {feature['properties']['id']
                                    for feature in existing_geojson['features']}
    else:
        existing_geojson = geojson.FeatureCollection([])
        existing_objects_ids = set()
    features = []
    for object in objects_data:
        name = object.get('tipeobj')
        ident = object.get('id')
        longitude = object.get('place_width')
        latitude = object.get('place_longitude')
        try:
            longitude = float(longitude)
            latitude = float(latitude)
        except (TypeError, ValueError):
            continue  # Skip if coordinates are invalid
        if ident not in existing_objects_ids:
            geometry = geojson.Point((longitude, latitude))
            features.append(geojson.Feature(geometry=geometry,
                            properties={"name": name, "id": ident}))
            existing_objects_ids.add(ident)
    geojson_data = geojson.FeatureCollection(features)
    if geojson_data:
        existing_geojson['features'].extend(geojson_data['features'])
    with open(geojson_objects_path, 'w', encoding='utf-8') as f:
        geojson.dump(existing_geojson, f)


@app.route('/objects-geodata')
def objects_data():
    return jsonify(objects_cache)


def process_regions(url, properties):
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download file: {response.status_code}")
    kml_content = response.content
    root = ET.fromstring(kml_content)
    features = []
    # properties = {"link": url}

    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    for placemark in root.findall('.//kml:Placemark', ns):
        extended_data = placemark.find(
            './/kml:ExtendedData/kml:SchemaData', ns)
        if extended_data is not None:
            for simple_data in extended_data.findall('kml:SimpleData', ns):
                if simple_data.attrib.get('name') == 'Наименование':
                    properties['name'] = simple_data.text or "N/A"
                elif simple_data.attrib.get('name') == 'Категория':
                    properties['category'] = simple_data.text or "N/A"
        polygon = placemark.find(
            './/kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)
        if polygon is not None:
            coords = polygon.text.strip()
            coordinates = [
                [float(coord) for coord in point.split(',')[:2]]
                for point in coords.split()
            ]
            geometry = geojson.Polygon([coordinates])
            features.append(geojson.Feature(
                geometry=geometry, properties=properties))

    feature_collection = geojson.FeatureCollection(features)
    return feature_collection


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
    coordinates = []
    for route in gpx.routes:
        for point in route.points:
            coordinates.append([point.longitude, point.latitude])
    geometry = geojson.LineString(coordinates)
    features.append(geojson.Feature(
        geometry=geometry, properties=route_properties))
    if features != []:
        for track in gpx.tracks:
            for segment in track.segments:
                coordinates = [[point.longitude, point.latitude]
                               for point in segment.points]
                geometry = geojson.LineString(coordinates)
                features.append(geojson.Feature(
                    geometry=geometry, properties=route_properties))
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
        features.append(geojson.Feature(
            geometry=geometry, properties=route_properties))
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
            features.append(geojson.Feature(
                geometry=geometry, properties=route_properties))

    feature_collection = geojson.FeatureCollection(features)
    return feature_collection


@app.route('/')
def home():
    return render_template('index.html')


load_routes()
load_regions()
load_equipment()
load_objects()

if __name__ == '__main__':
    app.run(port=5000, debug=True)
