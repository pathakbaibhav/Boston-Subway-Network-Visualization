import pygame
import csv

# Define colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Initialize Pygame
pygame.init()

# Set the width and height of the screen (width, height).
screen_size = (559, 559)
screen = pygame.display.set_mode(screen_size)

# Set the caption of the screen
pygame.display.set_caption("Node and Edge Visualization")

# Loop until the user clicks the close button.
done = False

# Used to manage how fast the screen updates
clock = pygame.time.Clock()

# Nodes and Edges
nodes = []
edges = []

# Load data from CSV files
def load_data():
    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Ex_1_2_3/locations.csv', mode='r') as locations_file:
        locations_reader = csv.reader(locations_file)
        for row in locations_reader:
            try:
                station_name, x, y = row
                nodes.append({'label': station_name, 'x': int(x), 'y': int(y)})
            except ValueError:
                # Skip rows with non-numeric data
                continue

    with open('/Users/baibhavpathak/Documents/Uni/Spring 2024/Assignments/Data Visualization/HW4-code/Ex_1_2_4/connections.csv', mode='r') as connections_file:
        connections_reader = csv.reader(connections_file)
        for row in connections_reader:
            try:
                station_a, station_b, col, minutes = row
                edges.append({'from': station_a, 'to': station_b, 'color': col, 'minutes': float(minutes)})
            except ValueError:
                # Skip rows with non-numeric data
                continue

def is_mouse_over_node(node):
    mouse_x, mouse_y = pygame.mouse.get_pos()
    return (mouse_x - node['x']) ** 2 + (mouse_y - node['y']) ** 2 <= 5 ** 2

load_data()

# Main Program Loop
while not done:
    # --- Main event loop
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            done = True

    # --- Game logic should go here

    # --- Drawing code should go here

    # First, clear the screen to white.
    screen.fill(WHITE)

    # Draw nodes
    hovered_node = None
    for node in nodes:
        pygame.draw.circle(screen, BLACK, (node['x'], node['y']), 5)
        if is_mouse_over_node(node):
            hovered_node = node

    # Draw edges
    for edge in edges:
        from_node = next((n for n in nodes if n['label'] == edge['from']), None)
        to_node = next((n for n in nodes if n['label'] == edge['to']), None)
        if from_node and to_node:
            pygame.draw.line(screen, BLACK, (from_node['x'], from_node['y']), (to_node['x'], to_node['y']), 1)

    # Display station name if mouse is over a node
    if hovered_node:
        font = pygame.font.Font(None, 24)
        text_surface = font.render(hovered_node['label'], True, BLACK)
        screen.blit(text_surface, (screen_size[0] - text_surface.get_width() - 10, 10))

    # --- Update the screen with what we've drawn.
    pygame.display.flip()

    # --- Limit to 60 frames per second
    clock.tick(60)

# Close the window and quit.
pygame.quit()
