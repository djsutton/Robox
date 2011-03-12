#!/usr/bin/env python

import code, sys, pdb, ctypes, copy, time, os, signal, traceback

from threading import Thread, Condition, Event, Lock, RLock, currentThread, _MainThread, enumerate as enumerateThreads
from math import pi,atan2,sin,cos

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import pango
import gtksourceview2

if sys.platform == 'win32':
    kernel32 = ctypes.windll.kernel32
    CTRL_C_EVENT = 0     # constants from http://msdn.microsoft.com/en-us/library/ms683155%28VS.85%29.aspx
    CTRL_BREAK_EVENT = 1 # this is in the win32con library, but that would be *another* download requirement
else:
    kernel32 = None

if not os.getcwd() in sys.path:
    sys.path = [os.getcwd()] + sys.path

class Robot(object):
    def __init__(self,x=0,y=0,heading=0):
        global environment
        
        self.x = x
        self.y = y
        self.heading = heading
        self.xextent = 10
        self.yextent = 10
        self.gc = None
        
        environment.robots.append(self)
        self.environment = environment
        
        self.lastDraw = self.drawingBoundingBox()
        self.queueRedraw()
    
    def getCanvas(self):
        return self.environment.canvas
    
    def queueRedraw(self):
        try:
            self.environment.canvas.widget.queue_draw_area(*(self.lastDraw))
            self.environment.canvas.widget.queue_draw_area(*self.drawingBoundingBox())
        except:
            pass # probably there is no canvas to draw to right now
    
    def boundingBox(self):
        return self.x-self.xextent, self.y-self.yextent,self.x+self.xextent,self.y+self.yextent
    
    def drawingBoundingBox(self):    
        x1,y1,x2,y2 = self.boundingBox()
        w,h = self.getCanvas().get_size()
        return int(x1+w/2),int(h/2-y2),int(x2+w/2),int(h/2-y1)
    
    def redraw(self, canvas, gc, x,y,w,h):
        w,h = self.getCanvas().get_size()
        drawx,drawy=self.x+w/2,self.y+h/2
        if (((x < drawx+self.xextent) or (x+w > drawx-self.xextent)) and
            ((y < drawy+self.yextent) or (y+h > drawy-self.yextent))):
            if self.gc:
                gc = self.gc
            self.draw(canvas,gc)
    
    def draw(self, canvas, gc):
        w,h = self.getCanvas().get_size()
        drawx,drawy=self.x+w/2,h/2-self.y
        canvas.draw_arc(gc, False, drawx-self.xextent,drawy-self.yextent,2*self.xextent,2*self.yextent,angle1=0,angle2=64*360)
        canvas.draw_line(gc,drawx,drawy,int(drawx+self.xextent*sin(self.heading*pi/180)),int(drawy-self.yextent*cos(self.heading*pi/180)))
        self.lastDraw=self.drawingBoundingBox()


class Environment(object):
    def __init__(self):
        self.robots=[]
        self.items=[]
        self.background = None


class TvConsole(object):
    def __init__(self,locals=None, getSource=None):
        self.inputLock = Lock() # lock for inputQueue, inputReady and interactiveLine
        self.inputReady = Condition(self.inputLock)
        self.inputPending = ''
        self.inputQueue = []
        self.interactiveLine = ''
        self.prompt = ''
        self.plen = len(self.prompt)
        self.history = []
        self.historyIndex = 0
        self.historyModified = {}
        self.cursor = 0
        self.incomplete = []
        self.EOF = False
        self.guiThread = currentThread() # best guess
        self.mainThread = list(t for t in enumerateThreads() if type(t) == _MainThread)[0] # best guess
        
        self.tv = gtk.TextView(buffer=None)
        self.tv.set_wrap_mode(gtk.WRAP_WORD)
        self.tv.set_editable(False)
        
        self.sw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.sw.add(self.tv)
        
        self.tv.add_events(gtk.gdk.KEY_PRESS)
        self.tv.connect('key-press-event',self.keyCallback)
        self.tv.connect('paste-clipboard', self.pasteCallback)
        self.tv.connect_after('populate-popup', self.popupCallback)
        self.tv.connect('destroy', self.stopInteracting)
        self.tv.set_cursor_visible(False)
        
        self.buffer = self.tv.get_buffer()
        self.vadj = self.sw.get_vadjustment()
        
        self.scrollToEnd = True;
        self.vadj.connect('changed', self.sizeCallback)
        self.vadj.connect('value-changed', self.scrollCallback)
        self.blockCursor = self.buffer.create_tag('cursor', background='black',foreground='white')
        
        self.pendingCR = False
        
        mono = pango.FontDescription('monospace 10')
        if mono:
            self.tv.modify_font(mono)
        
        self.writeBuffer = ''
        self.writeBufferLock = RLock()
        self.bufferLock = RLock()
        
        self.i2 = code.InteractiveInterpreter()
        self.i2.write = self.write
        self.i2.showtraceback = self.showtraceback
        self.setLocals({'__name__':'__main__'})
        if locals:
            self.setLocals(locals)
        
        self.getSource = getSource
        self.source = ''
        self.sourceLocals = set()
        
        if not hasattr(sys,'ps1'):
            sys.ps1 = '>>> '
        if not hasattr(sys,'ps2'):
            sys.ps2 =  '... '
        
        self.cursorOn = True
        self.running = Event()
    
    def start(self,main=True):
        
        gobject.timeout_add(600,self.toggleCursor)
        
        if main:
            self.interactiveThread = currentThread()
            self.interact()
        else:
            self.interactiveThread = Thread(target=self.interact,args=())
            self.interactiveThread.start()
    
    def setLocals(self,locals):
        self.i2.locals.update(locals)
    
    def stopInteracting(self, *args):
        self.running.clear()
        self.sendSigint()
        with self.inputLock:
            self.inputReady.notify()
    
    def interact(self):
        self.running.set() # This Event triggers the gtk main loop to 
                           # start, which must happen before the 
                           # blocking write below can succeed.
        
        sys.stdin = self
        sys.stdout = self
        sys.stderr = self
        
        self.write('Robo Interacive Python Interpreter\n' +
                    'Python ' + sys.version + ' on ' + sys.platform + 
                    '\nType "help", "copyright", "credits" or "license" for more information.\n')
        self.flush()
        self.prompt = sys.ps1
        self.cursor = 0
        gobject.idle_add(self.setInteractiveLine,'')
        
        while self.running.isSet():
            try:
                input = None
                with self.inputLock:
                    if not self.inputQueue:
                        self.inputReady.wait()
                    
                    if self.inputQueue:
                        input = self.inputQueue.pop(0)
                
                if input != None:
                    self.processInput(input)
            
            except KeyboardInterrupt:
                self.write('KeyboardInterrupt\n')
                self.flush()
                
                self.incomplete=[]
                self.prompt = sys.ps1
                
                setEvt=Event()
                gobject.idle_add(self.setInteractiveLine,self.interactiveLine, setEvt)
                setEvt.wait()
            
            except:
                traceback.print_exc(file=sys.__stdout__)
        
        sys.stderr = sys.__stderr__
        sys.stdout = sys.__stdout__
        sys.stdin = sys.__stdin__
    
    def processInput(self, input):
        self.prompt = ''
        preSetLine=Event()
        gobject.idle_add(self.setInteractiveLine,self.interactiveLine,preSetLine)
        preSetLine.wait()
        
        if input != None and self.running.isSet():
            
            incomplete = self.executeInput(input)
            self.flush()
            
            if incomplete:
                self.incomplete.append(input)
                self.prompt = sys.ps2
            else:
                self.incomplete=[]
                self.prompt = sys.ps1
            
            with self.inputLock:
                while self.inputQueue and not self.inputQueue[0]:
                    del self.inputQueue[0]
                
                if self.inputQueue:
                    nextLine = self.inputQueue[0]+'\n'
                else:
                    nextLine = self.interactiveLine
            
            postSetLine=Event()
            gobject.idle_add(self.setInteractiveLine,nextLine,postSetLine)
            postSetLine.wait()
    
    def executeInput(self,input):
        
        command = '\n'.join(self.incomplete+[input])
        
        source = None
        if self.getSource:
            source = self.getSource()
        
        try:
            if source:
                self.source = source
                try:
                    code = compile(source,'<code area>','exec')
                except (OverflowError, SyntaxError, ValueError) as e:
                    self.i2.showsyntaxerror('<code area>')
                else:
                    locals = self.i2.locals.copy()
                    oldSourceLocals = self.sourceLocals
                    
                    for key in oldSourceLocals:
                        try:
                            del self.i2.locals[key]
                        except:
                            pass
                    
                    oldKeys = self.i2.locals.keys()
                    
                    try:
                        exec code in self.i2.locals
                    except:
                        self.i2.showtraceback()
                    else:
                        self.sourceLocals=set(self.i2.locals.keys())-set(oldKeys)
            
            if not input:
                try:
                    compile(command+'\n','<stdin>','single')
                except IndentationError as e:
                    self.i2.showsyntaxerror('<stdin>')
                    return False
                except:
                    pass
            
            incomplete = self.i2.runsource(command,'<stdin>','single')
        finally:
            self.EOF = False
            self.softspace = 0
        
        return incomplete
    
    def showtraceback(self):
        """Display the exception that just occurred.
        This code is based on the same function from code.InteractiveInterpreter
        """
        try:
            type, value, tb = sys.exc_info()
            sys.last_type = type
            sys.last_value = value
            sys.last_traceback = tb
            tblist = traceback.extract_tb(tb)
            
            del tblist[0] # the first entry is the exec line from InteractiveInterpreter.runcode()
            i = 0
            while i < len(tblist):
                filename, lineno, function, line = tblist[i]
                if filename == '<code area>':
                    line = self.source.split('\n')[lineno-1]
                    tblist[i] = (filename, lineno, function, line)
                if filename == __file__:
                    del tblist[i:]
                i += 1
            
            lines = traceback.format_list(tblist)
            if lines:
                lines.insert(0, "Traceback (most recent call last):\n")
            lines.extend(traceback.format_exception_only(type, value))
        finally:
            tblist = tb = None
        self.write(''.join(lines))
    
    def doEntry(self):
        with self.inputLock:
            self.inputQueue.append(self.interactiveLine)
            self.updateHistory(self.interactiveLine)
            self.interactiveLine += '\n'
            
            self.cursor = 0
            self.cursorOn = True
            self.setInteractiveLine(self.interactiveLine)
            self.interactiveLine = ''
            self.prompt = ''
            self.inputPending = ''
            self.inputReady.notify()
        
        self.scrollToEnd = True
        self.autoScroll()
    
    def keyCallback(self,widget,event,data=None):
        
        string=''
        
        if event.string == '\r':
            self.doEntry()
            return True
        
        elif event.state & gtk.gdk.CONTROL_MASK:
            if event.keyval == ord('c') or event.keyval == ord('C'):
                if event.state & gtk.gdk.SHIFT_MASK:
                    event.state &= ~gtk.gdk.SHIFT_MASK
                else:
                    with self.inputLock:
                        self.interactiveLine += '^C\n'
                        self.inputPending = ''
                        self.inputQueue = []
                        if self.historyIndex in self.historyModified:
                            del self.historyModified[self.historyIndex]
                        self.historyIndex = len(self.history)
                        
                        self.cursor = 0
                        self.cursorOn = True
                        self.setInteractiveLine(self.interactiveLine)
                        self.interactiveLine = ''
                        self.prompt = ''
                        self.sendSigint()
                        self.inputReady.notify()
                    
                    self.scrollToEnd = True
                    self.autoScroll()
                    return True
            
            if event.keyval == ord('d') or event.keyval == ord('D'):
                self.EOF = True
                self.doEntry()
                return True
            
            if event.keyval == ord('v') or event.keyval == ord('V'):
                if event.state & gtk.gdk.SHIFT_MASK:
                    event.state &= ~gtk.gdk.SHIFT_MASK
            
            return False
        
        elif event.keyval == 65362: # up
            with self.inputLock:
                if self.historyIndex > 0:
                    oldIndex = self.historyIndex
                    self.historyIndex -= 1
                    
                    if self.historyIndex in self.historyModified:
                        self.interactiveLine = self.historyModified[self.historyIndex]
                    else:
                        self.interactiveLine = self.history[self.historyIndex]
                    
                    self.cursor = len(self.interactiveLine)
                    self.cursorOn = True
                    event.keyval = 0 # flow through to setInteractive line at the end of this block
                else:
                    self.scrollToEnd = True
                    self.autoScroll()
                    return True
        
        elif event.keyval == 65364: # down
            with self.inputLock:
                if self.historyIndex < len(self.history):
                    oldIndex = self.historyIndex
                    self.historyIndex += 1
                    
                    if self.historyIndex < len(self.history):
                        if self.historyIndex in self.historyModified:
                            self.interactiveLine = self.historyModified[self.historyIndex]
                        else:
                            self.interactiveLine = self.history[self.historyIndex]
                    else:
                        self.interactiveLine = self.inputPending
                
                    self.cursor = len(self.interactiveLine)
                    self.cursorOn = True
                    event.keyval = 0 # flow through to setInteractive line at the end of this block
                else:
                    self.scrollToEnd = True
                    self.autoScroll()
                    return True
        
        elif event.keyval == 65361: # left
            with self.inputLock:
                if self.cursor > 0:
                    self.cursor -= 1
                    self.cursorOn = True
                    self.updateCursor()
            self.scrollToEnd = True
            self.autoScroll()
            return True
        
        elif event.keyval == 65363: # right
            with self.inputLock:
                if self.cursor < len(self.interactiveLine):
                    self.cursor += 1
                    self.cursorOn = True
                    self.updateCursor()
            self.scrollToEnd = True
            self.autoScroll()
            return True
        
        elif event.keyval == 65288: #backspace
            with self.inputLock:
                if self.cursor > 0:
                    self.interactiveLine = self.interactiveLine[:self.cursor-1]+self.interactiveLine[self.cursor:]
                    self.cursor -= 1
                    if self.historyIndex < len(self.history):
                        self.historyModified[self.historyIndex] = self.interactiveLine
                    self.cursorOn = True
                    self.updateCursor()
                    event.keyval = 0 # flow through to setInteractive line at the end of this block
                else:
                    self.scrollToEnd = True  
                    self.autoScroll()
                    return True
        
        elif event.keyval == 65289: #tab
            event.keyval = ord('\t')
            string = '\t'
        else:
            string = event.string
        
        if event.keyval < 256:
            if string:
                self.insertAtCursor(string)
            self.setInteractiveLine(self.interactiveLine)
            self.scrollToEnd = True
            self.autoScroll()
        
        return True
    
    def insertAtCursor(self,string):
        with self.inputLock:
            head = self.interactiveLine[:self.cursor]
            tail = self.interactiveLine[self.cursor:]
            text = head + string + tail
            lines = text.split('\n')
            while lines:
                self.interactiveLine = lines.pop(0)
                if self.historyIndex < len(self.history):
                    self.historyModified[self.historyIndex] = self.interactiveLine
                else:
                    self.inputPending = self.interactiveLine
                if lines:
                    self.doEntry()
            
            self.cursor = len(self.interactiveLine)-len(tail)
    
    def pasteCallback(self,widget):
        clip = gtk.Clipboard()
        text = clip.wait_for_text()
        
        if text:
            self.insertAtCursor(text)
            self.setInteractiveLine(self.interactiveLine)
        
        return False
    
    def popupCallback(self,widget, menu):
        clip = gtk.Clipboard()
        if clip.wait_is_text_available():
            self.menu = menu
            for child in menu.get_children():
                if child.get_label() == 'gtk-paste':
                    child.set_sensitive(True)
        return True
    
    def updateHistory(self, input):
        if (not self.history or self.history[-1] != input) and input:
            self.history.append(input)
        
        if self.historyIndex in self.historyModified:
            del self.historyModified[self.historyIndex]
        self.historyIndex = len(self.history)    
    
    def read(self,size=-1,lines=-1):
        
        if size == 0:
            return '\n'
        
        input = ''
        reading = True
        
        while reading and not self.EOF:
            with self.inputLock:
                
                if not self.inputQueue:
                    self.inputReady.wait()
            
                if self.inputQueue:
                    while self.inputQueue and reading:
                        if size > 0:
                            fragment = (self.inputQueue[0]+'\n')[:size]
                            self.inputQueue[0] = self.inputQueue[0][size:]
                            if not self.inputQueue[0]:
                                del self.inputQueue[0]
                                lines -= 1
                                if lines == 0:
                                    reading = False
                            input += fragment
                            size -= len(fragment)
                            if size <= 0:
                                reading = False
                        else:
                            input += self.inputQueue.pop(0)+'\n'
                            lines -= 1
                            if lines == 0:
                                reading = False
        
        return input
    
    def readline(self,size=-1):
        return self.read(size,1)
    
    def readlines(self,sizehint=-1):
        lines=[]
        
        if sizehint < 0:
            sizehint = None
        
        while not self.EOF or (sizehint and sum(len(line) for line in lines) < sizehint):
            lines.append(self.readline())
        
        if lines[-1] == '\n':
            lines = lines[:-1]
        
        return lines
    
    def bufferOutput(self,string):
        string = string.replace('\r\n','\n')
        start,end = string.startswith('\r'),string[1:].endswith('\r')
        string = string.strip('\r')
        
        lines = [line.rsplit('\r',1)[-1] for line in string.split('\n')]
        
        if start:
            head,sep,tail = self.writeBuffer.rpartition('\n')
            self.writeBuffer = head+sep or '\r'
        
        self.writeBuffer += '\n'.join(lines)
        
        if end:
            self.writeBuffer += '\r'
    
    def writeHelper(self,string):
        with self.writeBufferLock:
            callNeeded = not self.writeBuffer
            self.bufferOutput(string)
        currentThread().callNeeded = callNeeded
        return callNeeded
    
    def write(self, string, blocking=False):
        if currentThread() == self.mainThread:
            # workaround to block SIGINT from this section 
            # since Lock.acquire() handles it poorly
            t=Thread(target=self.writeHelper,name='WriteHelperThread',args=(string,))
            t.start()
            t.join()
            callNeeded = t.callNeeded
        else:
            callNeeded = self.writeHelper(string)
        
        if self.guiThread == currentThread() and blocking:
            self.insertEnd(blocking = True)
        else:
            if callNeeded:
                self.pendingWrite=Event()
                gobject.idle_add(self.insertEnd, self.pendingWrite, priority = gobject.PRIORITY_HIGH)
            
            if blocking:
                self.pendingWrite.wait()
    
    def flush(self):
        with self.writeBufferLock:
            callNeeded = bool(self.writeBuffer)
        if callNeeded:
            if self.guiThread == currentThread():
                self.insertEnd()
            else:
                self.pendingWrite=Event()
                gobject.idle_add(self.insertEnd, self.pendingWrite, priority = gobject.PRIORITY_HIGH)
        
        if self.guiThread != currentThread():
            self.pendingWrite.wait()
    
    def insertEnd(self,writeEvt=None, blocking=False):
        
        writeBufferRelease = self.writeBufferLock.release
        
        if self.writeBufferLock.acquire(blocking):
            try:
                if self.bufferLock.acquire(blocking):
                    try:
                        string = self.writeBuffer
                        self.writeBuffer = ''
                        
                        writeBufferRelease()
                        writeBufferRelease = None
                        
                        cr = self.pendingCR or string.startswith('\r')
                        self.pendingCR = string.endswith('\r')
                        string = string.strip('\r')
                        
                        if string:
                            self.setInteractiveLine('')
                        
                            # remove the trailing space for the cursor
                            end = self.buffer.get_end_iter()
                            iter = end.copy()
                            iter.backward_char()
                            self.buffer.delete(iter, end)
                            
                            iter.set_line_offset(0)
                            cleanIter=iter.copy()
                            cleanIter.backward_lines(4) # workaround for a gtkTextView line wrap bug
                            clean = self.buffer.create_mark(None,cleanIter,left_gravity=True)
                            
                            if cr:
                                self.buffer.delete(iter, end)
                            
                            self.buffer.insert(end,string)
                            self.buffer.remove_tag_by_name('cursor',self.buffer.get_iter_at_mark(clean),end)
                            self.buffer.delete_mark(clean)
                            
                            if cr:
                                self.prompt=''
                            self.prompt = (self.prompt + string).split('\n')[-1]
                            self.plen = len(self.prompt)
                            self.setInteractiveLine(self.interactiveLine)
                            
                            self.updateCursor()
                        
                        if writeEvt:
                            writeEvt.set()
                        return False #no need to call this function again
                    finally:
                        self.bufferLock.release()
                else:
                    return True #call this function again
            finally:
                if writeBufferRelease:
                    writeBufferRelease()
        else:
            return True #call this function again
    
    def scrollCallback(self, adj):
        self.scrollToEnd =  adj.get_value() == adj.get_upper()-adj.get_page_size()
    
    def sizeCallback(self,widget,data=None):
        # called when the size of self.vadj changes
        self.autoScroll()
    
    def autoScroll(self):
        if self.scrollToEnd:
            cursor = self.buffer.get_end_iter()
            if cursor.get_chars_in_line() > self.plen+self.cursor:
                cursor.set_line_offset(self.plen+self.cursor)
            cursorMark = self.buffer.create_mark(None,cursor,left_gravity=True)
            self.tv.scroll_mark_onscreen(cursorMark)
            self.buffer.delete_mark(cursorMark)
    
    def setInteractiveLine(self,string,writeEvt=None):
        with self.bufferLock:
            end = self.buffer.get_end_iter()
            iter = self.buffer.get_end_iter()
            iter.set_line_offset(0)
            self.buffer.delete(iter, end)
            end = self.buffer.get_end_iter()
            
            string = self.prompt + string
            self.plen = len(self.prompt)
            
            if string.endswith('\n'):
                self.plen = 0
            self.buffer.insert(end,string+' ') # blank space for cursor at EOL
            
            self.updateCursor(False)
        if writeEvt:
            writeEvt.set()
        return False
    
    def updateCursor(self, clear=True):
        
        cursor = self.buffer.get_end_iter()
        if cursor.get_chars_in_line() > self.plen+self.cursor:
            cursor.set_line_offset(self.plen+self.cursor)
        cursorPlus1 = cursor.copy()
        cursorPlus1.forward_char()
        
        if clear or not self.cursorOn:
            start = cursor.copy()
            end = cursorPlus1.copy()
            start.backward_char()
            end.forward_char()
            self.buffer.remove_tag_by_name('cursor',start,end)
        
        if self.cursorOn:
            self.buffer.apply_tag_by_name('cursor',cursor,cursorPlus1)
        else:
            if not clear:
                self.buffer.remove_tag_by_name('cursor',cursor,cursorPlus1)
    
    def toggleCursor(self):
        self.cursorOn = not self.cursorOn
        self.updateCursor(False)
        return True;
    
    def sendSigint(self):
        if kernel32:
            kernel32.GenerateConsoleCtrlEvent(CTRL_C_EVENT,0)
        else:
            os.kill(os.getpid(),signal.SIGINT)


class Gui(object):
    def delete_evt(self,widget,event,data=None):
        # False -> destroy window
        # True -> dont destroy window
        return False
    
    def __init__(self):
        global environment
        
        self.window = gtk.Window()
        self.width = 0
        self.height = 0
        self.window.connect('delete-event', self.delete_evt)
        self.window.connect('configure-event', self.configure_window)
        self.window.set_title('Robo')
        self.window.set_default_size(800, 600)
        
        self.hpane = gtk.HPaned()
        self.hpane.proportion=0
        self.hpane.width=0
        self.hpane.update = True
        self.hpane.connect('expose-event', self.expose_pane)
        self.hpane.positionHandler = self.hpane.connect('notify::position', self.reposition_pane)
        
        self.vpane = gtk.VPaned()
        self.vpane.proportion=0
        self.vpane.height=0
        self.vpane.update = True
        self.vpane.connect('expose-event', self.expose_pane)
        self.vpane.positionHandler = self.vpane.connect('notify::position', self.reposition_pane)
        
        self.lm = gtksourceview2.LanguageManager()
        
        buffer = gtksourceview2.Buffer()
        
        buffer.set_data('languages-manager', self.lm)
        buffer.set_language(self.lm.get_language('python'))
        buffer.set_highlight_syntax(True)
        buffer.set_highlight_matching_brackets(True)
        
        self.codeTv = gtksourceview2.View(buffer)
        self.codeTv.set_indent_width(4)
        self.codeTv.set_tab_width(4)
        self.codeTv.set_insert_spaces_instead_of_tabs(True)
        self.codeTv.set_indent_on_tab(True)
        self.codeTv.set_highlight_current_line(True)
        self.codeTv.set_auto_indent(True)
        self.codeTv.set_show_line_numbers(True)
        
        mono = pango.FontDescription('monospace 10')
        if mono:
            self.codeTv.modify_font(mono)
        
        self.codeSw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.codeSw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.codeSw.add_with_viewport(self.codeTv)
        
        self.load_code(undoable = False)
        self.codeModified = True
        
        self.graphics = gtk.DrawingArea()
        self.graphics.connect("configure-event", self.configure_graphics)
        self.graphics.connect("expose-event", self.push_graphics)
        
        environment = Environment()
        self.canvas = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        self.canvas.widget = self.graphics.window
        environment.canvas = self.canvas
        self.drawing = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        environment.drawing = self.drawing
        self.background = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        environment.background = self.background
        
        locals={'gui':self,'Gui':Gui, 'environment':environment, 'Robot':Robot}
        self.console = TvConsole(locals=locals, getSource=self.get_code)
        
        self.hpane.add1(self.vpane)
        self.hpane.add2(self.codeSw)
        
        self.vpane.add1(self.graphics)
        self.vpane.add2(self.console.sw)
        
        self.window.add(self.hpane)
        
        self.window.show_all()
        
        self.vpane.set_position(0)
        self.hpane.set_position(self.hpane.get_property('max-position'))
    
    def save_code(self,force=False):
        srcBuffer = self.codeTv.get_buffer()
        modified = srcBuffer.get_modified()
        if modified or force:
            source = srcBuffer.get_text(*srcBuffer.get_bounds())
            source = source.replace('\r\n','\n')
            
            if source[-1] != '\n':
                source += '\n'
            if modified:
                with open('source.py','wb') as f:
                    f.write(source)
                srcBuffer.set_modified(False)
                self.codeModified = True
        else:
            source=None
        
        return source
    
    def get_code(self):
        source = self.save_code(self.codeModified)
        self.codeModified = False
        return source
    
    def load_code(self,filename='source.py',undoable=True):
        loadThread = Thread(target=self.asynchronus_load_code, name='LoadCode', args=(filename, undoable))
        loadThread.daemon = True
        loadThread.start()
    
    def asynchronus_load_code(self,filename='source.py',undoable=True):
        try:
            f=open(filename)
            text=f.read()
            f.close()
        except IOError:
            pass
        except Exception as e:
            traceback.print_exc(file=sys.__stdout__)
        else:
            text = text.replace('\r\n','\n')
            gobject.idle_add(self.set_code, text, undoable)
    
    def set_code(self,code,undoable=True):
        srcBuffer = self.codeTv.get_buffer()
        
        if not undoable:
            srcBuffer.begin_not_undoable_action()
        
        srcBuffer.set_text(code)
        srcBuffer.set_modified(False)
        
        if not undoable:
            srcBuffer.end_not_undoable_action()
    
    def configure_window(self, window, event):
        x,y,w,h = window.get_allocation()
        
        if w != self.width:
            self.hpane.update = False
            self.width = w
        
        if h != self.height:
            self.vpane.update = False
            self.height = h
    
    def expose_pane(self, pane, event):
        x,y,w,h = pane.get_allocation()
        if pane == self.hpane:
            resized = self.hpane.width != w
            self.hpane.width = w
        else:
            resized = self.vpane.height != h
            self.vpane.height = h
        
        if resized:
            pane.update = False
            self.reallocatePane(pane)
        
        pane.update = True
    
    def reallocatePane(self,pane):
        maxPos = pane.get_property('max-position')
        minPos = pane.get_property('min-position')
        position = int(round(minPos + (maxPos-minPos)*pane.proportion))
        pane.set_position(position)
    
    def reposition_pane(self, widget, property_spec):
        if widget.update:
            maxPos = widget.get_property('max-position')
            minPos = widget.get_property('min-position')
            widget.proportion = (widget.get_position()-minPos)/float(maxPos-minPos)
    
    def configure_graphics(self, widget, event):
        
        x,y,w,h = widget.get_allocation()
        self.canvas = gtk.gdk.Pixmap(widget.window, w, h, depth=-1)
        environment.canvas = self.canvas
        self.canvas.widget = widget
        self.drawing = gtk.gdk.Pixmap(widget.window, w, h, depth=-1)
        environment.drawing = self.drawing
        self.background = gtk.gdk.Pixmap(widget.window, w, h, depth=-1)
        environment.background = self.background
        self.background.draw_rectangle(widget.get_style().white_gc,True, x,y, w, h)
        self.drawing.draw_rectangle(widget.get_style().white_gc,True, x,y, w, h)
        return True
    
    def push_graphics(self,widget,event):
        x,y,w,h = event.area
        self.canvas.draw_rectangle(widget.get_style().white_gc,True, x,y, w, h)
        self.canvas.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],self.background, x, y, x, y, w, h)
        self.canvas.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],self.drawing, x, y, x, y, w, h)
        for obj in environment.robots+environment.items:
            obj.redraw(self.canvas, widget.get_style().black_gc, x,y,w,h)
        widget.window.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],self.canvas, x, y, x, y, w, h)
        return False
    
    def main(self):
        self.console.running.wait() # console.interactiveThread must be set
                                    # correctly before proceeding.
        
        while self.console.interactiveThread.isAlive():
            try:
                with gtk.gdk.lock:
                    while gtk.events_pending():
                        gtk.main_iteration(False)
                    time.sleep(.001)
            except:
                traceback.print_exc(file=sys.__stdout__)


gui = None

def makeGui(guiReady=None, runGui=True):
    global gui
    try:
        gui = Gui()
        gui.console.guiThread=currentThread()
    except:
        traceback.print_exc(file=sys.__stdout__)
    finally:
        if guiReady:
            guiReady.set()
    
    if gui and runGui:
            gui.main()

def main(consoleMain=True):
    
    guiReady = Event()
    guiReady.clear()
    
    if not kernel32:
        gtk.gdk.threads_init()
    
    try:
        if consoleMain:
            Thread(target=makeGui, name="GUIThread", args=(guiReady,)).start()
        else:
            makeGui(guiReady, False)
        
        guiReady.wait() # gui thread must fully initialize console component
        
        gui.console.mainThread = currentThread()
        
        if gui:
            gui.console.start(consoleMain)
        
            if not consoleMain:
                gui.main()
    
    except Exception as e:
        traceback.print_exc(file=sys.__stdout__)
    return gui

if __name__ == '__main__':
    main()
