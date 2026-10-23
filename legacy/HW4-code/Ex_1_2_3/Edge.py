class Edge:
    def __init__(self, from_node, to_node, minutes):
        self.from_node = from_node
        self.to_node = to_node
        self.minutes = minutes

    def get_from_node(self):
        return self.from_node

    def get_to_node(self):
        return self.to_node

    def get_minutes(self):
        return self.minutes

    def draw(self):
        # Assuming a drawing function similar to Processing's line()
        stroke(0)
        stroke_weight(1)
        line(self.from_node.x, self.from_node.y, self.to_node.x, self.to_node.y)
