all_lines = []

for i in range(1, 4):
    with open(f"albums{i}.txt", "r") as this_file:
        this_file_lines = this_file.readlines()
        all_lines.extend(this_file_lines)

sorted_all_lines = sorted(all_lines)

with open("all_albums.txt", "w") as all_albums_file:
    all_albums_file.writelines(sorted_all_lines)
