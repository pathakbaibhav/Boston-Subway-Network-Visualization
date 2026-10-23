class Node:
    def __init__(self, label, x, y, index):
        self.label = label
        self.x = x
        self.y = y
        self.index = index

    def get_index(self):
        return self.index

    def draw(self):
        # Assuming a drawing function similar to Processing's ellipse()
        stroke(0)
        stroke_weight(1)
        fill(255)
        ellipse(self.x, self.y, 5, 5)
