"""Native jukebox music discs, using the loader's normal item registration."""
from fabricpy.item import Item


class MusicDisc(Item):
    """An item that plays a sound in a vanilla jukebox.

    ``sound`` is a sound resource path, with its OGG file in
    ``assets/<modid>/sounds/<sound>.ogg``. It can also name an existing
    namespaced sound event. The compiler creates local sound registrations,
    streaming sound metadata, native disc behavior, and song descriptions.
    """

    sound: str = ""
    length_seconds: int | float = 180
    comparator_output: int = 15
    artist: str = ""
    title: str = ""
    max_stack_size: int = 1
    rarity: str = "rare"
