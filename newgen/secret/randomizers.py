"""Small, dependency-free random value generators."""

import secrets

ADJECTIVES = [
    "Quiet", "Gentle", "Brave", "Calm", "Kind", "Bright", "Soft", "Steady",
    "Warm", "Clear", "Humble", "Honest", "Silent", "Golden", "Silver", "Blue",
    "Green", "Amber", "Swift", "Mellow", "Noble", "Peaceful", "Hopeful",
    "Curious", "Thoughtful", "Radiant", "Daring", "Patient", "Fearless",
    "Tender", "Wandering", "Sunny", "Starry", "Misty", "Coastal", "Highland",
    "Forest", "River", "Desert", "Island", "Northern", "Southern", "Eastern",
    "Western", "Morning", "Evening", "Midnight", "Dawn", "Twilight", "Open",
]

ANIMALS = [
    "Lion", "Dove", "Eagle", "Owl", "Panther", "Tiger", "Falcon", "Heron",
    "Otter", "Fox", "Wolf", "Deer", "Antelope", "Gazelle", "Dolphin",
    "Whale", "Turtle", "Butterfly", "Firefly", "Sparrow", "Robin", "Swallow",
    "Kite", "Crane", "Pelican", "Ibis", "Cobra", "Python", "Gecko",
    "Chameleon", "Meerkat", "Badger", "Hedgehog", "Squirrel", "Rabbit",
    "Leopard", "Cheetah", "Buffalo", "Elephant", "Giraffe", "Zebra",
    "Hippo", "Rhino", "Camel", "Donkey", "Goat", "Sheep", "Pigeon",
    "Kingfisher", "Woodpecker", "Hummingbird", "Peacock", "Parrot",
]

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def random_alias() -> str:
    """Return a friendly alias such as ``Quiet Lion 42``.

    The number suffix keeps the namespace large enough for many institutions
    while remaining easy to read and remember.
    """
    return (
        f"{secrets.choice(ADJECTIVES)} {secrets.choice(ANIMALS)} "
        f"{secrets.randbelow(90) + 10}"
    )


def random_room_code(length: int = 6) -> str:
    """Return a numeric room code. Our rooms use 4 or 6 digits."""
    length = 4 if length == 4 else 6
    return "".join(str(secrets.randbelow(10)) for _ in range(length))
