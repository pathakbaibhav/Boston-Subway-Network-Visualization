import pygame
import csv

# Initialize pygame
pygame.init()

# Set up the display
screen = pygame.display.set_mode((559, 559))
pygame.display.set_caption("MBTA Map")

# Load the map image
map_image = pygame.image.load("mbta-map.gif")

# Load station names and coordinates from CSV
name_table = []
with open("/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Ex_1_2_2/stations.csv", "r") as csvfile:
    csvreader = csv.reader(csvfile)
    for row in csvreader:
        name_table.append(row)

# Create a writer for the output CSV
output_file = open("locations.csv", "w", newline="")
writer = csv.writer(output_file)

# Set up variables for tracking the current row and whether recording is finished
current_row = 0
recording_finished = False

# Main loop
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and not recording_finished:
            print("Mouse clicked")
            if current_row < len(name_table):
                station_name = name_table[current_row][0]
                x_coord = str(event.pos[0])
                y_coord = str(event.pos[1])
                print("Recording:", station_name, x_coord, y_coord)
                writer.writerow([station_name, x_coord, y_coord])
                current_row += 1
            if current_row == len(name_table):
                recording_finished = True
                print("Recording finished")
                output_file.close()

    # Clear the screen and draw the map
    screen.fill((0, 0, 0))
    screen.blit(map_image, (0, 0))

    # Display station names on the map
    font = pygame.font.Font(None, 24)
    for i, row in enumerate(name_table):
        station_name = row[0]
        text = font.render(station_name, True, (255, 255, 255))
        screen.blit(text, (50, 50 + i * 20))

    # Update the display
    pygame.display.flip()

# Quit pygame
pygame.quit()
