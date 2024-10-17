from bs4 import BeautifulSoup

# Read the HTML file
with open("data.html", "r") as file:
    html_content = file.read()

# Parse the HTML
soup = BeautifulSoup(html_content, "html.parser")

# Find the table with connections
connections_table = soup.find_all("table")[1]

# Extract connections
connections = [
    [cell.text for cell in row.find_all("td")[1:]]  # Skip the first column (index)
    for row in connections_table.find_all("tr")[1:]
]

# Write to connections.csv
with open("connections.csv", "w") as file:
    file.write("From,To,Color,Minutes\n")  # Write the header
    for connection in connections:
        file.write(",".join(connection) + "\n")
