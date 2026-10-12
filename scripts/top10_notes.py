"""Hand-written commentary for the ten selected games, keyed by Steam appid.

Every observation restates a number from the stored run or a plain reading of it. Remarks that
draw on outside knowledge are marked as such. Wording is hedged on purpose: the data is a single
scan and the unit estimates are review-based.
"""
from __future__ import annotations

GAME_NOTES: dict[int, dict[str, object]] = {
    2231450: {  # Pizza Tower
        "observations": [
            "It has the largest estimated net revenue of the 76-game pool (about $21.3M) at a C of 0.237, which is the 43rd percentile and not the low end. The position comes from volume and not from a very low complexity score.",
            "Its 2.28M estimated units are about 27 times the median of the Comedy archetype (84,550 units). The archetype's demand score is a median and does not describe a typical member, so this title behaves as an outlier inside its archetype.",
            "The Boxleiter mid estimate lies above the SteamSpy owner band (1M to 2M), so the revenue figure may be overstated.",
            "The most-voted tags are Great Soundtrack (980 votes), 2D Platformer, Fast-Paced, Cartoony and Funny. The data cannot separate the contribution of audio, art style and gameplay to its reception.",
            "The price of $13.39 is at the 88th percentile of the pool and the game still ranks first in review count, which may suggest that demand for it was not strongly price-limited.",
        ],
        "reading": "It may indicate that a stylized 2D platformer with a strong audio and visual identity can reach a large audience at a mid price. As a template it carries survivorship risk, because it is a single outlier of its archetype.",
    },
    813230: {  # ANIMAL WELL
        "observations": [
            "The 35 MB install size is the 1st percentile of the pool and is the main reason for its low C of 0.162. This probably does not reflect production effort, because install size also depends on how assets are generated and compressed.",
            "At $17.49 it is at the 93rd percentile of price, with 13,049 reviews and 95.3% positive. A premium price was therefore compatible with a strong reception in this archetype.",
            "The mid estimate of 652k units is above the SteamSpy band (200k to 500k), so the true figure may be closer to the band.",
            "It is published by Bigmode and is not self-published. It carries only one of the three label tags of its archetype (Platformer), and its most-voted tags are Metroidvania, Exploration and Puzzle.",
            "The Platformer archetype has 23 games and Ω = +0.17, the weakest positive score among the six archetypes except Point & Click.",
        ],
        "reading": "The commercial result is clear in the data, but its C is the least trustworthy of the ten. It is better read as evidence that a premium-priced puzzle-platformer can sell well than as a low-effort template.",
    },
    2212330: {  # Your Only Move Is HUSTLE
        "observations": [
            "At $3.99 it has an estimated 1.56M units, and the mid estimate lies within the SteamSpy band (1M to 2M). This is the best corroborated of the three highest-ranked games, since the first two lie above their bands.",
            "C is 0.161 (8th percentile of the pool). The game lists one language, 22 achievements and no DLC, and its categories include Online PvP and LAN PvP.",
            "The most-voted tags are 2D Fighter, Turn-Based Strategy, Spectacle fighter and Sandbox. It combines two genres that are usually separate, and its archetype assignment rests on Hand-drawn (130 votes) and Cartoony (146 votes), which rank lower among its tags.",
            "Online and local multiplayer modes may add networking and balancing work that the complexity score does not fully capture.",
        ],
        "reading": "The low price and the large estimated volume may suggest a volume-driven pricing approach. The multiplayer component makes the effort for a small team uncertain.",
    },
    2365810: {  # Pseudoregalia
        "observations": [
            "At $4.19 and with 14,066 reviews (97.1% positive) it has an estimated 703k units, within the SteamSpy band (500k to 1M).",
            "C is 0.256. The minimum RAM requirement is 8 GB and the install size is 600 MB. The achievement count is missing in the stored data and was imputed.",
            "It is a 3D platformer with Metroidvania, Parkour and Old School tags. Its only stored label tag of the Minimalist archetype is Surreal (160 votes), so the archetype fit is loose.",
            "The Minimalist archetype holds exactly 5 games, which is the scoring floor, and its D of +2.04 rests on a median of five values.",
        ],
        "reading": "The game may show that a low-priced 3D platformer can reach a large audience. The archetype it sits in has the thinnest evidence of the six.",
    },
    1562700: {  # SANABI
        "observations": [
            "The developer (WONDER POTION) and the publisher (NEOWIZ) differ, so this is not a self-published result.",
            "The estimated 239k units are below the SteamSpy band (500k to 1M), which suggests that the review-based figure may be conservative or that the band overstates the audience.",
            "It lists 11 languages and 21 achievements. The 1 GB install size is at the 58th percentile of the pool. C is 0.262.",
            "Among its tags, Pixel Graphics, Story Rich and Cyberpunk have the most votes. It carries all three label tags of the Platformer archetype.",
        ],
        "reading": "It has a more conventional production profile than the games above, with localization and a publisher. It may be a less direct reference for a very small self-funded team.",
    },
    2487350: {  # Alex Jones: NWO Wars
        "observations": [
            "C is 0.155 (4th percentile of the pool) and the game lists one language. The achievement count is missing in the stored data and was imputed.",
            "At $17.76 it has the highest price of the selection and an estimated 84.6k units, below the SteamSpy band (100k to 200k).",
            "It is a 2D side-scrolling shooter with Conspiracy and America tags. The title refers to a public figure, and the data cannot separate audience that follows that figure from audience for the genre.",
            "Only 1,691 reviews support its estimate, the smallest review base of the ten, so its ranking is the least stable.",
        ],
        "reading": "Its replicability may be limited if a significant share of demand depended on the associated public figure. The data cannot confirm this.",
    },
    824600: {  # HROT
        "observations": [
            "At $6.79 it has 3,794 reviews (96.1% positive) and an estimated 190k units, which is about 5 times the median of the Retro archetype (35,372 units). The mid estimate sits just below the SteamSpy band (200k to 500k) and its low-to-high range (152k to 247k) overlaps it.",
            "C is 0.185 (17th percentile of the pool). It lists 2 languages, 55 achievements, Steam Trading Cards and a long list of accessibility options.",
            "The most-voted tags are Retro, FPS, Shooter and Boomer Shooter, so it sits in a defined niche whose audience identifies the genre by name.",
            "Developer and publisher are the same name, which suggests a self-published release.",
        ],
        "reading": "It is a compact retro shooter with a modest price, and the data may suggest that a clearly named niche can support a self-published release of this size.",
    },
    2637990: {  # Duck Detective
        "observations": [
            "At $7.49 it has 4,840 reviews (95.0% positive) and an estimated 179k units, within the SteamSpy band (100k to 200k). That is about 18 times the median of the Point & Click archetype (9,725 units).",
            "The Point & Click archetype has Ω = +0.11, the weakest positive score of the six, so the game is a strong member of a weakly supported archetype.",
            "The tags include Detective, Investigation, Casual, Short (98 votes), Cute and Noir. A short length may keep scope small.",
            "It lists three platforms, the only one of the ten to do so, and 19 Steam category entries, most of them accessibility and controller options. It has only 7 achievements and 4 languages.",
        ],
        "reading": "The data may suggest that a short, tightly scoped narrative game can reach a mid-sized audience. Its C is raised somewhat by the three-platform release.",
    },
    3107330: {  # Nodebuster
        "observations": [
            "At $1.94 it has 10,648 reviews (97.2% positive) and an estimated 287k units, within the SteamSpy band (200k to 500k). The estimated net revenue of about $390k is the second smallest of the ten, so its E rank is lifted mainly by the lowest C of the selection (0.139, 1st percentile of the pool).",
            "It is a clicker and idle game (Clicker, Idler, Strategy, Casual). It lists one language and a 100 MB install size.",
            "It shares the Minimalist archetype with Pseudoregalia although the two games have little in common in design. The archetype is a cluster of similar tag sets and not a design lineage.",
        ],
        "reading": "It may suggest that a very low-price, low-scope game can still reach a large number of buyers. The absolute revenue is small, so it points to a different business outcome than the games above.",
    },
    1889040: {  # Birth
        "observations": [
            "At $4.94 it has 2,639 reviews (96.8% positive) and an estimated 97.6k units, below the SteamSpy band (200k to 500k). Its estimated net revenue of about $338k is the smallest of the ten.",
            "C is 0.263 (61st percentile of the pool) with a 2 GB install size, which is the 86th percentile of the pool. The RAM requirement was imputed.",
            "The most-voted tags are Point & Click, Surreal, Puzzle, Relaxing and Hidden Object. It carries Stylized (110 votes) and Hand-drawn (108 votes) of its archetype's label tags.",
            "The Stylized archetype has 6 games and its median is 39,617 units, so Birth is about 2.5 times the median.",
        ],
        "reading": "It is on the list because of the two-games-per-archetype rule and carries the weakest evidence of the ten. It should be read as a modest, low-risk result.",
    },
}
