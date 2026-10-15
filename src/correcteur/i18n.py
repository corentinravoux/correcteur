"""Interface language: English, or French.

Strings are written in English in the code and looked up here with ``_()``.
The language follows the system locale unless ``interface`` is set in the
configuration. Messages from the engines stay in the language of the text.
"""

from __future__ import annotations

import locale
import os

_language = "en"

FR = {
    # Main window
    "Paste && check": "Coller && vérifier",
    "Check": "Vérifier",
    "Accept all": "Tout accepter",
    "Copy text": "Copier le texte",
    "Style suggestions": "Suggestions de style",
    "Exceptions": "Exceptions",
    "Exceptions ({n})": "Exceptions ({n})",
    "Auto": "Auto",
    "Français": "Français",
    "English (US)": "Anglais (US)",
    "English (UK)": "Anglais (R.-U.)",
    "Paste your text here, then press Check.\n\nUnderlined words have a suggestion: click one to fix it.":
        "Collez votre texte ici, puis appuyez sur Vérifier.\n\n"
        "Les mots soulignés ont une suggestion : cliquez sur l’un d’eux pour le corriger.",
    "Auto detects the language of each paragraph": "Auto détecte la langue de chaque paragraphe",
    "Also flag wordiness, repetitions and other matters of style":
        "Signaler aussi les longueurs, les répétitions et d’autres questions de style",
    "Skip LaTeX commands, maths and comments; check only the prose.\n"
    "Ticked automatically when pasted text looks like LaTeX.":
        "Ignorer les commandes LaTeX, les formules et les commentaires ; ne vérifier que le texte.\n"
        "Coché automatiquement quand le texte collé ressemble à du LaTeX.",
    "Replace the text with the clipboard and check it": "Remplacer le texte par le presse-papiers et le vérifier",
    "Check the text": "Vérifier le texte",
    "Apply the first suggestion of every issue; Ctrl+Z undoes it":
        "Appliquer la première suggestion de chaque point ; Ctrl+Z annule",
    "Copy the whole text to the clipboard": "Copier tout le texte dans le presse-papiers",
    "Rules turned off, ignored issues and dictionary words":
        "Règles désactivées, points ignorés et mots du dictionnaire",
    # Status
    "Starting LanguageTool…": "Démarrage de LanguageTool…",
    "Ready to check with {engines}.": "Prêt à vérifier avec {engines}.",
    " and ": " et ",
    "LanguageTool is not running.": "LanguageTool ne fonctionne pas.",
    "LanguageTool is not running. Close Correcteur and open it again.":
        "LanguageTool ne fonctionne pas. Fermez Correcteur et rouvrez-le.",
    "Nothing to check yet: paste or type some text.": "Rien à vérifier : collez ou tapez du texte.",
    "Checking…": "Vérification…",
    "Starting LanguageTool, then checking…": "Démarrage de LanguageTool, puis vérification…",
    "The text changed during the check. Press Check again.":
        "Le texte a changé pendant la vérification. Appuyez de nouveau sur Vérifier.",
    "Some results are missing: the text may be too long.":
        "Certains résultats manquent : le texte est peut-être trop long.",
    "The check failed.": "La vérification a échoué.",
    "The check failed": "La vérification a échoué",
    "LanguageTool did not start": "LanguageTool n’a pas démarré",
    "No suggestion to apply.": "Aucune suggestion à appliquer.",
    "Applied {n} suggestion. Ctrl+Z undoes it.": "{n} suggestion appliquée. Ctrl+Z l’annule.",
    "Applied {n} suggestions. Ctrl+Z undoes them.": "{n} suggestions appliquées. Ctrl+Z les annule.",
    "Turned off “{rule}”.": "Règle « {rule} » désactivée.",
    "No issue left.": "Plus rien à revoir.",
    "Enter applies the suggestion, the arrows choose another, Esc stops.":
        "Entrée applique la suggestion, les flèches en choisissent une autre, Échap arrête.",
    "The clipboard is empty.": "Le presse-papiers est vide.",
    "Text copied.": "Texte copié.",
    "LaTeX detected: commands and maths are skipped. Checking…":
        "LaTeX détecté : commandes et formules ignorées. Vérification…",
    "{n} issue in {language}": "{n} point à revoir en {language}",
    "{n} issues in {language}": "{n} points à revoir en {language}",
    "No issues in {language}": "Aucun point à revoir en {language}",
    " (text edited since the check)": " (texte modifié depuis la vérification)",
    "Not added: a dictionary entry is one word, without spaces, not starting with #.":
        "Non ajouté\u00a0: une entrée du dictionnaire est un seul mot, sans espace, qui ne commence pas par #.",
    "Configuration error": "Erreur de configuration",
    # Menu and margin
    "No suggestion": "Aucune suggestion",
    "&Skip": "&Passer",
    "&Ignore": "&Ignorer",
    "Ignore": "Ignorer",
    "&Add “{word}” to the {language} dictionary": "&Ajouter « {word} » au dictionnaire {language}",
    "Add “{word}” to the dictionary of all &languages":
        "Ajouter « {word} » au dictionnaire de toutes les &langues",
    "&Turn off this rule": "&Désactiver cette règle",
    "Add to dictionary": "Ajouter au dictionnaire",
    "Add “{word}” to the {language} dictionary": "Ajouter « {word} » au dictionnaire {language}",
    "Add “{word}” to the dictionary of all languages":
        "Ajouter « {word} » au dictionnaire de toutes les langues",
    "Turn off rule": "Désactiver la règle",
    "Never flag this again for this text": "Ne plus signaler ceci pour ce texte",
    "Never apply this rule again": "Ne plus appliquer cette règle",
    "Show in the text": "Montrer dans le texte",
    "Replace with “{replacement}”": "Remplacer par « {replacement} »",
    "(delete)": "(supprimer)",
    "{n} to review": "{n} à revoir",
    "{n} more, shown in the text.": "{n} de plus, visibles dans le texte.",
    "Issues appear here after a check.": "Les points à revoir apparaissent ici après une vérification.",
    "No issues found.": "Rien à signaler.",
    "spelling": "orthographe",
    "grammar": "grammaire",
    "style": "style",
    "typography": "typographie",
    # Languages
    "French": "français",
    "English": "anglais",
    "all languages": "toutes les langues",
    "All languages": "Toutes les langues",
    # Exceptions window
    "Rules turned off ({n})": "Règles désactivées ({n})",
    "Ignored ({n})": "Ignorés ({n})",
    "Dictionary ({n})": "Dictionnaire ({n})",
    "These rules are never applied. Turn one back on to see its issues at the next check.":
        "Ces règles ne sont jamais appliquées. Réactivez-en une pour voir ses points à la prochaine vérification.",
    "These issues were ignored and are never flagged again for the same text.":
        "Ces points ont été ignorés et ne sont plus signalés pour le même texte.",
    "Words that are never flagged as misspelt, for every language or for one.":
        "Mots jamais signalés comme fautes d’orthographe, pour toutes les langues ou pour une seule.",
    "Rule": "Règle",
    "Identifier": "Identifiant",
    "Text": "Texte",
    "Word": "Mot",
    "Language": "Langue",
    "Turn back on": "Réactiver",
    "Flag again": "Signaler de nouveau",
    "Remove": "Retirer",
    "New word": "Nouveau mot",
    "Add": "Ajouter",
    "Filter": "Filtrer",
}

# Names of languages as LanguageTool reports them, in French.
_LANGUAGE_WORDS = {"French": "français", "English": "anglais", "Catalan": "catalan", "German": "allemand",
                   "Spanish": "espagnol", "Italian": "italien", "Portuguese": "portugais", "Dutch": "néerlandais"}


def setup(choice: str = "auto") -> str:
    """Pick the interface language: "fr", "en", or "auto" for the system's."""
    global _language
    if choice == "auto":
        lang = os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") \
            or os.environ.get("LANG") or (locale.getlocale()[0] or "")
        choice = "fr" if lang.lower().startswith("fr") else "en"
    _language = "fr" if choice == "fr" else "en"
    return _language


def current() -> str:
    return _language


def _(text: str, **values) -> str:
    if _language == "fr":
        text = FR.get(text, text)
    return text.format(**values) if values else text


def ngettext(singular: str, plural: str, n: int, **values) -> str:
    return _(singular if n == 1 else plural, n=n, **values)


def language_name(name: str) -> str:
    """A language name from LanguageTool, such as "English (US)", in the interface language."""
    if _language != "fr":
        return name
    for english, french in _LANGUAGE_WORDS.items():
        name = name.replace(english, french)
    return name
