from bs4 import BeautifulSoup

# Read the HTML file
with open("data.html", "r") as file:
    html_content = file.read()

# Parse the HTML
soup = BeautifulSoup(html_content, "html.parser")

# Find the table with station names
stations_table = soup.find_all("table")[0]

# Extract station names
stations = [row.find_all("td")[1].text for row in stations_table.find_all("tr")[1:]]

# Write to stations.csv
with open("stations.csv", "w") as file:
    for station in stations:
        file.write(f"{station}\n")
