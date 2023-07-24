import requests
import csv
import folium
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Set your Geoapify API key
API_KEY = ("")

# Get today's date
today = date.today().strftime("%d-%m-%Y")

# Create the 'data' directory if it doesn't exist
data_directory = f"data/{today}"
if not os.path.exists(data_directory):
    os.makedirs(data_directory)

# Function to geocode addresses using Geoapify API
def geocode_address(address):
    url = f"https://api.geoapify.com/v1/geocode/search?text={address}&apiKey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    if response.status_code == 200 and data["features"]:
        feature = data["features"][0]
        coordinates = tuple(reversed(feature["geometry"]["coordinates"]))
        return coordinates
    return None

# Set the headers for the GET request
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Send the GET request to the website with the headers
url = 'https://www.keysso.net/arrests'
response = requests.get(url, headers=headers)

# Parse the HTML content with BeautifulSoup
soup = BeautifulSoup(response.content, 'html.parser')

# Find all rows
div_rows = soup.find_all('div', class_='row')

# Variables needed
data_list = []
coordinates_list = []
image_urls = []
markers = []

# Iterate over each row element and extract the information
for div_row in div_rows:
    if div_row.find('ul', id='arrest-list') is None:
        continue

    # Extract the data
    arrest_list = div_row.find('ul', id='arrest-list')

    name_elem = arrest_list.find('span', id='arrest-name')
    if name_elem is not None:
        name = name_elem.strong.text.strip()
    else:
        name = 'Unknown'

    info_list_items = arrest_list.find_all('li')
    info_dict = {}
    charges = []
    for item in info_list_items:
        item_text = item.text.strip()
        if item_text.startswith("Date of Birth:"):
            info_dict['Date of Birth'] = item.find('strong').text.strip()
            age_index = item_text.index("Age:")
            gender_index = item_text.index("Gender:")
            race_index = item_text.index("Race:")
            info_dict['Age'] = item_text[age_index + 4:gender_index].strip()
            info_dict['Gender'] = item_text[gender_index + 7:race_index].strip()
            info_dict['Race'] = item_text[race_index + 5:].strip()
        elif item_text.startswith("Address:"):
            info_dict['Address'] = item.find('strong').text.strip()
        elif item_text.startswith("Occupation:"):
            info_dict['Occupation'] = item.find('strong').text.strip()
        elif item_text.startswith("Arrest Location:"):
            arrest_location = item.find('strong').text.strip()
            if arrest_location == "," or arrest_location is None:
                info_dict['Arrest Location'] = 'Unknown'
            else:
                info_dict['Arrest Location'] = arrest_location + ', Florida'
        elif item_text.startswith("Charges:"):
            charges = list(set([charge.strong.text.strip() for charge in item.find_next('ul').find_all('li')]))

    # Change gender value
    gender = info_dict.get('Gender', 'Gender is unavailable')
    if gender == 'M':
        gender = 'Male'
    elif gender == 'F':
        gender = 'Female'

    # Change race value
    race = info_dict.get('Race', 'Race is unavailable')
    if race == 'B':
        race = 'Black'
    elif race == 'W':
        race = 'White'

    # Extract the image URL
    image_url_elem = div_row.find('img', class_='img-thumbnail')
    if image_url_elem is not None:
        image_url = image_url_elem['src']
        image_name = f"{os.path.basename(name)}.jpg"
        image_path = os.path.join(data_directory, image_name)
        image_urls.append((image_url, image_path))
    else:
        image_path = ''

    # Add the extracted data to the list
    data_list.append({
        'Name': name,
        'Date of Birth': info_dict.get('Date of Birth', 'Unknown'),
        'Age': info_dict.get('Age', 'Age is unavailable'),
        'Gender': gender,
        'Race': race,
        'Address': info_dict.get('Address', 'Unknown'),
        'Occupation': info_dict.get('Occupation', 'Unknown'),
        'Arrest Location': info_dict.get('Arrest Location', 'Unknown'),
        'Charges': charges,
        'Image Path': image_path
    })

    # Add the Arrest location to the coordinates list for mapping
    coordinates_list.append(info_dict.get('Arrest Location', 'Unknown'))

# Save the data to a CSV file
csv_filename = f"{data_directory}/arrests-{today}.csv"
with open(csv_filename, 'w', newline='') as csvfile:
    fieldnames = ['Name', 'Date of Birth', 'Age', 'Gender', 'Race', 'Address', 'Occupation', 'Arrest Location', 'Charges', 'Image Path']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data_list)

# Create the map
m = folium.Map(location=[24.5545, -81.80023], zoom_start=10)

# Download the images in parallel
def download_image(url, filename):
    response = requests.get(url)
    with open(filename, 'wb') as image_file:
        image_file.write(response.content)

with ThreadPoolExecutor() as executor:
    for data, coordinates, (image_url, image_path) in zip(data_list, coordinates_list, image_urls):
        if coordinates == 'Unknown':
            continue
        future = executor.submit(geocode_address, coordinates)
        future.data = data
        future.image_path = image_path

        def on_image_downloaded(future):
            download_image(future.image_url, future.image_path)

        future.image_url = image_url
        future.add_done_callback(on_image_downloaded)
        markers.append(future)

# Add all the markers to the map
for marker in markers:
    coordinates = marker.result()
    if coordinates is not None:
        data = marker.data
        image_path = marker.image_path

        # Create the HTML for the marker popup
        popup_html = f"""
        <strong>Name:</strong> {data['Name']}<br>
        <strong>Date of Birth:</strong> {data['Date of Birth']}<br>
        <strong>Gender:</strong> {data['Gender']}<br>
        <strong>Race:</strong> {data['Race']}<br>
        <strong>Address:</strong> {data['Address']}<br>
        <strong>Arrest Location:</strong> {data['Arrest Location']}<br>
        <strong>Charges:</strong><br>
        """
        for charge in data['Charges']:
            popup_html += f"- {charge}<br>"
        popup_html += f'<img src="{os.path.basename(image_path)}" alt="{data["Name"]}" width="250" height="200" style="display: block; margin: 0 auto;">'

        # Determine the icon color based on charges
        icon_color = 'red' if any('Felony' in charge for charge in data['Charges']) else 'orange'

        # Create the marker
        folium.Marker(
            location=coordinates,
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=icon_color, icon='info-sign', prefix='fa')
        ).add_to(m)


# Add layers to the map
folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                 name='Esri Satellite',
                 attr='Esri Satellite').add_to(m)

folium.LayerControl().add_to(m)

# Save the map as an HTML file
map_filename = f"{data_directory}/arrest_map-{today}.html"
m.save(map_filename)


# Extract relevant crime type from the charges
def get_relevant_crime(charge):
    relevant_crime_types = ['FAILURE TO APPEAR', 'RESIST OFFICER', 'PROB VIOLATION', 'LARCENY', 'DRUG POSSESSION', 'BATTERY', 'TRESPASSING', 'DUI', 'COCAINE-POSSESS', 'DRUG EQUIP-POSSESS', 'LARC', 'MOVING TRAFFIC VIOL', 'DISORDERLY CONDUCT', 'SEX ASSLT', 'INTIMIDATION', 'FRAUD-IMPERSON', 'FRAUD', 'INDECENT EXPOSURE', 'STALKING', 'MARIJUANA-POSSESS', 'CONDIT RELEASE', 'CONSERVATION']
    for crime_type in relevant_crime_types:
        if crime_type in charge:
            return crime_type
    return 'Other'

# Convert the charges column to a pandas Series
df = pd.read_csv(csv_filename)
charges_series = df['Charges'].explode()

# Extract relevant crime types from the end of each charge
relevant_charges = charges_series.apply(get_relevant_crime)

# Get the counts of each relevant crime type
crime_counts = relevant_charges.value_counts()

# Plot the bar chart for all charges
plt.figure(figsize=(12, 12))
ax = sns.barplot(x=crime_counts.index, y=crime_counts.values, orient='v')
plt.title('All Crime Types', fontsize=20)  
plt.xlabel('Crime Type', fontsize=16) 
plt.ylabel('Count', fontsize=16)
plt.xticks(rotation=45, fontsize=8)  

# Add labels for each bar with smaller font size
for index, value in enumerate(crime_counts.values):
    ax.text(index, value, str(value), ha='center', va='bottom', fontsize=8)  

plt.savefig(f"{data_directory}/all_crime_types.png", dpi=300)
plt.show()