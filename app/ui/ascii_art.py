"""ASCII animation frames for loading states.

Each animation is a list of equal-spirited multiline frames cycled by a timer.
Kept in monospace; rendered in a QLabel with a fixed-width font.
"""

# Cat reading a book — used while the LLM scans the text for characters.
READING_CAT = [
    r"""
   /\_/\      ____
  ( o.o )    |    |
   > ^ <     |    |
  /     \    |____|
 reading.
""",
    r"""
   /\_/\      ____
  ( -.- )    |    |
   > ^ <     |====|
  /     \    |____|
 reading..
""",
    r"""
   /\_/\      ____
  ( o.o )    |====|
   > ^ <     |====|
  /     \    |____|
 reading...
""",
    r"""
   /\_/\      ____
  ( ^.^ )    |====|
   > ^ <     |====|
  /     \    |____|
 reading....
""",
]

# Cat talking into a microphone — used while TTS audio is generated.
MIC_CAT = [
    r"""
    /\_/\
   ( o.o )      .---.
   ( -   )=====<| O |
    > ^ <        '---'
   recording.
""",
    r"""
    /\_/\    )
   ( o.o )   )  .---.
   ( O   )=====<| O |
    > ^ <    )   '---'
   recording..
""",
    r"""
    /\_/\   ))
   ( o.o )  )) .---.
   ( O   )=====<| O |
    > ^ <   ))  '---'
   recording...
""",
    r"""
    /\_/\    )
   ( o.o )   )  .---.
   ( -   )=====<| O |
    > ^ <    )   '---'
   recording..
""",
]
