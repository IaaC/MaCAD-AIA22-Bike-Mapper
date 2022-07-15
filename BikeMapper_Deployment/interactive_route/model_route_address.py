#This script re-weights the streets according to user preference and outputs a geojson of the route

#imports
import pandas as pd
import numpy as np
import networkx as nx
import osmnx as ox
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point
from shapely.geometry import LineString
import requests
import json
gpd.options.use_pygeos = True

def call(safetyPref, litPref, surfacePref, vegPref, windPref, lengthPref, source_address, target_address):

    ####### load relevant files of preprocessed data #####################################################

    #get preprocessed data for edges
    scoredEdges = pd.read_csv('finalScoredEdges.csv')
    #get preprocessed data for nodes
    nodes_df = pd.read_csv('nodes.csv') #need to change this file path

    ############# clean data ########################################################################

    #convert string to shapely linestring
    scoredEdges['geometry'] = scoredEdges['geometry'].apply(wkt.loads)

    #convert edges to gdf
    scoredEdges_gdf = gpd.GeoDataFrame(scoredEdges, crs='EPSG:4326', geometry=scoredEdges['geometry'])

    #clean edge data and set appropriate index
    scoredEdges_gdf = scoredEdges_gdf.drop(columns=['Unnamed: 0', 'index'])
    scoredEdges_gdf = scoredEdges_gdf.set_index(['u', 'v', 'key'])


    ##############  WIND ######################################################################################

    #get windspeed and direction (using free rapid api account so can't make more than 500 requests a month)
    MY_API_KEY = "4561471e50msh3d1e762ef5340e0p12521djsn5f37f41058cd"

    url = "https://community-open-weather-map.p.rapidapi.com/weather"

    querystring = {"q":"Vienna, Austria","lat":"0","lon":"0","callback":"","id":"2172797","lang":"null","units":"metric"}

    headers = {
        "X-RapidAPI-Host": "community-open-weather-map.p.rapidapi.com",
        "X-RapidAPI-Key": "4561471e50msh3d1e762ef5340e0p12521djsn5f37f41058cd"
    }

    response = requests.request("GET", url, headers=headers, params=querystring)

    #convert response to json
    data = json.loads(response.text)

    #parse json for relevent data
    windDirection = data['wind']['deg']
    windSpeed = data['wind']['speed']
    print(windDirection, windSpeed)

    #check which wind column direction to use
    if windDirection > 337.5 and windDirection < 22.5:
        wCol = 'w1'
    elif windDirection > 22.5 and windDirection < 67.5:
        wCol = 'w2'
    elif windDirection > 67.5 and windDirection < 112.5:
        wCol = 'w3'
    elif windDirection > 112.5 and windDirection < 157.5:
        wCol = 'w4'
    elif windDirection > 157.5 and windDirection < 202.5:
        wCol = 'w5'
    elif windDirection > 202.5 and windDirection < 247.5:
        wCol = 'w6'
    elif windDirection > 247.5 and windDirection < 292.5:
        wCol = 'w7'
    else:
        wCol = 'w8'

    #create wind scores
    windSpeedList = scoredEdges[wCol]*windSpeed
    windScore = []
    for i in range(len(windSpeedList)):
        if windSpeedList[i] < 1.8:
            windScore.append(0)
        elif windSpeedList[i] > 1.8 and windSpeedList[i] < 3.6:
            windScore.append(0.25)
        elif windSpeedList[i] > 3.6 and windSpeedList[i] < 5.3:
            windScore.append(0.50)
        elif windSpeedList[i] > 5.3 and windSpeedList[i] < 7.6:
            windScore.append(0.75)
        elif windSpeedList[i] > 7.6:
            windScore.append(1)
        else: 
            windScore.append(0.25)

    #add wind score to dataframe
    scoredEdges_gdf['windScore'] = windScore

    ########### make combined score #############################################################################

    #preferences:  0, 1 to 5,  0: don't include in weight, 1: weight the least, 5: weight the most
    combinedScore = np.array(safetyPref*scoredEdges['safetyScore']) + np.array(litPref*scoredEdges['litScore']) + np.array(surfacePref*scoredEdges['pavedScore']) + np.array(lengthPref*scoredEdges['lengthMod']) + np.array(vegPref*scoredEdges['vegScore'] + np.array(windPref*scoredEdges_gdf['windScore']))
    scoredEdges_gdf['combinedScore'] = combinedScore

    #convert node csv to df to gdf
    node_df = pd.DataFrame(
    {'y': list(nodes_df['y']),
     'x': list(nodes_df['x'])})

    node_gdf = gpd.GeoDataFrame(node_df, geometry=gpd.points_from_xy(node_df.x, node_df.y))
    node_gdf['osmid'] = list(nodes_df['osmid'])
    node_gdf = node_gdf.set_index('osmid')

    #make graph 
    G_weighted = ox.graph_from_gdfs(node_gdf, scoredEdges_gdf)

    #Find node closest to start and end points
    # Source
    source_location= ox.geocode(source_address) 
    source_point = Point(source_location[1], source_location[0])

    # Target
    target_location = ox.geocode(target_address) 
    target_point = Point(target_location[1], target_location[0])

    #Get index of nearest nodes in the graph for the source and target locations
    source_index = node_gdf.sindex.nearest(source_point, return_all=False)
    target_index = node_gdf.sindex.nearest(target_point, return_all=False)

    #get osmid of nearest node
    source_node = list(node_gdf.iloc[[source_index[1][0]]].index)[0]
    target_node = list(node_gdf.iloc[[target_index[1][0]]].index)[0]

    #Calculate best route
    route = ox.distance.shortest_path(G_weighted, source_node, target_node, weight = 'combinedScore')

    #route node osmid to geometry to json
    lat_list = list(node_gdf.loc[route].x)
    long_list = list(node_gdf.loc[route].y)

    route_geom = LineString(zip(lat_list, long_list))
    route_geojson = gpd.GeoSeries([route_geom]).to_json()

    return route_geojson