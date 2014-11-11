import urwid
import tempfile
import subprocess
import os
from wikicurses import formats
from wikicurses import settings
from wikicurses.wiki import Wiki
from wikicurses.htmlparse import parseDisambig

def tabComplete(text, matches):
    if not matches:
        return text
    matches = sorted(matches, key=len)
    if matches[0] == text and len(matches)>1:
        match = matches[1]
    else:
        match = matches[0]
    return match

class SearchBox(urwid.Edit):
    title = "Search"
    def keypress(self, size, key):
        if key == 'enter':
            closeOverlay()
            openPage(self.edit_text or 'Main page')
        elif key == 'tab':
            matches = wiki.search_sugestions(self.edit_text)
            match = tabComplete(self.edit_text, matches)
            self.set_edit_text(match)
            self.edit_pos = len(match)
        elif key == 'esc':
            closeOverlay()
        else:
            return super().keypress(size, key)

class SelectorBox(urwid.ListBox):
    def __init__(self):
        def selectButton(radio_button, new_state, parameter):
            if new_state:
                closeOverlay()
                self._select(parameter)

        super().__init__(urwid.SimpleFocusListWalker([]))
        buttons = []
        for i, item in enumerate(self._items()):
            if isinstance(item, urwid.Widget):
                self.body.append(item)
                continue
            elif isinstance(item, tuple):
                name, selected, parameter = item
            else:
                parameter = name = item
                selected = False
            self.body.append(urwid.RadioButton(buttons, name, selected,
                selectButton, parameter))
            if selected:
                self.set_focus(i)

    def keypress(self, size, key):
        if key == 'esc':
            closeOverlay()
        else:
            return super().keypress(size, key)

class Toc(SelectorBox):
    title = "Table of Contents"
    def _items(self):
        for name, ind in mainwidget.body.widgetnames:
            yield name, mainwidget.body.body.focus>=ind, ind
    
    def _select(self, index):
       mainwidget.body.body.set_focus(index)

class Bmarks(SelectorBox):
    title = "Bookmarks"
    def _items(self):
        self.deleted = []
        return wiki.bmarks

    def _select(self, name):
        openPage(name)

    def keypress(self, size, key):
        #Undo Delete
        if key == 'u' and self.deleted:
            index, item = self.deleted.pop()
            wiki.bmarks.add(item.label)
            self.body.insert(index, item)
            self.set_focus(index)
        elif key in ('meta [', 'x') and self.focus:
            wiki.bmarks.discard(self.focus.label)
            self.deleted.append((self.focus_position, self.focus))
            self.body.remove(self.focus)
        else:
            return super().keypress(size, key)

class Wikis(SelectorBox):
    title = "Wikis"
    def _items(self):
        for name, url in settings.wikis().items():
            yield name, wiki.siteurl == url, name

    def _select(self, name):
        openWiki(name)
        openPage('Main page')

class Feeds(SelectorBox):
    title = "Feeds"
    def _items(self):
        return wiki.list_featured_feeds()

    def _select(self, feed):
        openPage(feed, True)

class Ex(urwid.Edit):
    def keypress(self, size, key):
        if key == 'esc' or (key == 'backspace' and not self.edit_text):
            self.exitexmode()
        elif key == 'tab':
            matches = [i for i in cmds if i.startswith(self.edit_text)]
            match = tabComplete(self.edit_text, matches)
            self.set_edit_text(match)
            self.edit_pos = len(match)
        elif key == 'enter':
            words = self.edit_text.split(' ')
            self.exitexmode()
            processCmd(*words)
        else:
            return super().keypress(size, key)

    def exitexmode(self):
        self.set_caption('')
        self.set_edit_text('')
        mainwidget.set_focus('body')

    def enterexmode(self):
        mainwidget.set_focus('footer')
        self.set_caption(':')

class StandardKeyBinds:
    def keypress(self, size, key):
        if not isinstance(mainwidget.footer, urwid.Edit):
            mainwidget.footer = Ex()

        cmdmap = settings.conf['keymap']
        if key == ':':
            mainwidget.footer.enterexmode()
        elif key in ('g', 'home'):
            self.set_focus(0)
            self.render(size)
        elif key in ('G', 'end'):
            self.set_focus(len(self.body)-1)
            self.render(size)
        elif key in cmdmap and cmdmap[key]:
            processCmd(cmdmap[key])
        else:
            return super().keypress(size, key)

class Disambig(StandardKeyBinds, SelectorBox):
    widgetnames = []
    def __init__(self, html):
        self.sections = parseDisambig(html)
        super().__init__()

    def _items(self):
        for title, items in self.sections.items():
            if title:
                yield urwid.Text(['\n', ('h', title)], align='center')
            for name, text in items:
                yield (text, False, name) if name else urwid.Text(text)

    def _select(self, name):
        openPage(name)

class Results(StandardKeyBinds, SelectorBox):
    widgetnames = []
    def __init__(self, results):
        self.results = results
        super().__init__()

    def _items(self):
        return self.results

    def _select(self, title):
        openPage(title)

class Pager(StandardKeyBinds, urwid.ListBox):
    def __init__(self, page):
        super().__init__(urwid.SimpleFocusListWalker([]))
        self.widgetnames = []
        for title, content in page.content.items():
            if title:
                h2 = urwid.Text([('h2', title), '\n'], align="center")
                self.body.append(h2)
                self.widgetnames.append((title, self.body.index(h2)))
            else:
                self.widgetnames.append((page.title, 0))
            self.body.append(urwid.Text(list(content)))

def openPage(title, featured=False):
    if featured:
        page = wiki.get_featured_feed(title)
    else:
        page = wiki.search(title)
    if not page.exists:
        results = wiki.search_sugestions(page.title)
        if results:
            header.set_text('Results for ' + title)
            mainwidget.body = Results(results)
    elif 'disambiguation' in page.properties:
        header.set_text(page.title + ': Disambiguation')
        mainwidget.body = Disambig(page.result['text']['*'])

    else:
        header.set_text(page.title)
        mainwidget.body = Pager(page)

def openWiki(name):
    global wiki
    if not name:
        name = settings.conf['general']['default']
    if name in settings.conf:
        url = settings.conf[name]['url']
        username = settings.conf[name].get('username')
        password = settings.conf[name].get('password')
    else:
        url = name
        username = password = ''
    wiki = Wiki(url, username, password)

def edit(title):
    init = wiki.init_edit(title)
    if not init:
        notify('Unable to Edit: Page Not Found')
        return
    text, verify = init
    error = wiki.login()
    if error:
        notify('Login Failed: ' + error)
        return

    with tempfile.NamedTemporaryFile('w+') as file:
        file.write(text)
        file.flush()
        subprocess.call([os.environ.get('EDITOR', 'vim'), file.name])
        file.seek(0)
        newtext = file.read()

    if newtext == text:
        notify('Edit Canceled: No Change')
        return

    def submit(button):
        closeOverlay()
        wiki.commit_edit(title, newtext, summary.edit_text,
                minor.get_state(), verify)
        openPage(title)
    summary = urwid.Edit('Summary: ')
    minor = urwid.CheckBox('Minor Edit')
    submit_button = urwid.Button('Submit', submit)
    openOverlay(urwid.Pile([summary, minor, submit_button]), 'Edit', 'pack')

cmds = ('quit', 'bmark', 'bmarks', 'wikis', 'feeds',
        'open', 'contents', 'edit', 'clearcache')
def processCmd(cmd, *args):
    if cmd in ('q', 'quit'):
        raise urwid.ExitMainLoop
    elif cmd == 'bmark':
        wiki.bmarks.add(header.text)
        notify("Bookmark Added")
    elif cmd in ('bmarks' ,'wikis', 'feeds', 'contents'):
        openOverlay({'bmarks':Bmarks,
                     'wikis':Wikis,
                     'feeds':Feeds,
                     'contents':Toc}[cmd]())
    elif cmd == 'open':
        if args:
            openPage(' '.join(args))
        else:
            openOverlay(SearchBox())
    elif cmd == 'clearcache':
        wiki.clear_cache()
    elif cmd == 'edit':
        edit(header.text)
    elif cmd:
        notify(cmd + ': Unknown Command')

def notify(text):
    mainwidget.footer = urwid.Text(text)

def openOverlay(widget, title=None, height=('relative', 50), width=('relative', 50)):
    if widget._sizing == {'flow'}:
        height = 'pack'
    box = urwid.LineBox(widget, title or widget.title)
    overlay = urwid.Overlay(box, mainwidget, 'center', width, 'middle', height)
    loop.widget = overlay

def closeOverlay():
    loop.widget = mainwidget


palette = [('h1', 'bold', 'dark blue'),
           ('h2', 'underline', ''),
           ('h', 'underline', '')]

#(ITALIC, 'italic') does not work. No italics option?
outputfmt = (('b', 'bold'), ('blockquote', 'dark gray'))
for x in range(1, sum(formats) + 1):
    fmt = ','.join(j for i, j in outputfmt if x&formats[i])
    palette.append((x, fmt, ''))

urwid.command_map['k'] = 'cursor up'
urwid.command_map['j'] = 'cursor down'
urwid.command_map['ctrl b'] = 'cursor page up'
urwid.command_map['ctrl f'] = 'cursor page down'

header = urwid.Text('Wikicurses', align='center')
loading = urwid.Filler(urwid.Text('Loading...'), 'top')
mainwidget = urwid.Frame(loading, urwid.AttrMap(header, 'h1'), Ex())
loop = urwid.MainLoop(mainwidget, palette=palette, handle_mouse=False)
