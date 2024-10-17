import csv

class Table:
    def __init__(self, filename=None):
        self.data = []
        self.row_count = 0

        if filename:
            self.load(filename)

    def load(self, filename):
        with open(filename, 'r', newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            for row in reader:
                row = [item.strip() for item in row]  # Trim whitespace
                if len(row) == 0 or row[0].startswith('#'):
                    continue  # Skip empty or comment lines
                self.data.append(row)
                self.row_count += 1

    def get_row_count(self):
        return self.row_count

    def get_row_index(self, name):
        for i, row in enumerate(self.data):
            if row[0] == name:
                return i
        print(f"No row named '{name}' was found")
        return -1

    def get_row_name(self, row):
        return self.data[row][0]

    def get_string(self, row, column):
        return self.data[row][column]

    def get_int(self, row, column):
        return int(self.data[row][column])

    def get_float(self, row, column):
        return float(self.data[row][column])

    def set_row_name(self, row, value):
        self.data[row][0] = value

    def set_string(self, row, column, value):
        self.data[row][column] = value

    def set_int(self, row, column, value):
        self.data[row][column] = str(value)

    def set_float(self, row, column, value):
        self.data[row][column] = str(value)

    def write(self, filename):
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter='\t')
            for row in self.data:
                writer.writerow(row)

# Example usage:
# table = Table('somefile.csv')
# table.set_string(0, 1, 'Hello')
# table.write('output.tsv')
