#!/usr/bin/env python

import code, sys, pdb, ctypes, copy, time, os, signal, traceback

from threading import Thread, Event, Lock, currentThread
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
        self.inputReady = Event()
        self.inputWaiting = Event()
        self.inputPending = ''
        self.ipLock = Lock()
        self.interactiveLine = ''
        self.history = []
        self.historyIndex = 0
        self.historyModified = {}
        self.cursor = 0
        self.incomplete = []
        self.EOF = False
        self.guiThread = None
        
        self.tv = gtk.TextView(buffer=None)
        self.tv.set_wrap_mode(gtk.WRAP_WORD)
        self.tv.set_editable(False)
        self.tv.connect("destroy", self.stopReadLoop)
        
        self.sw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.sw.add_with_viewport(self.tv)
        
        self.tv.add_events(gtk.gdk.KEY_PRESS)
        self.tv.connect('key_press_event',self.keyCallback)
        self.tv.set_cursor_visible(False)
        
        self.buffer = self.tv.get_buffer()
        self.vadj = self.sw.get_vadjustment()
        
        self.scrollToEnd = True;
        self.sw.connect_after('size-allocate', self.scrollCallback)
        self.blockCursor = self.buffer.create_tag('cursor', background='black',foreground='white')
        
        self.pendingCR = False
        
        mono = pango.FontDescription('monospace 10')
        if mono:
            self.tv.modify_font(mono)
        
        self.text=''
        self.textLock=Lock()
        
        self.i2 = code.InteractiveInterpreter()
        self.i2.write = self.write
        if locals:
            self.setLocals(locals)
        
        self.getSource = getSource
        
        self.ps1 = (sys.ps1 if hasattr(sys,'ps1') else '>>> ')
        self.ps2 = (sys.ps2 if hasattr(sys,'ps2') else '... ')
        self.plen = 0
        self.cursorOn = True
        self.running = Event()
        self.running.clear()
    
    def start(self,main=True):
        
        gobject.timeout_add(600,self.toggleCursor)
        
        if main:
            self.readLoopThread = currentThread()
            self.readLoop()
        else:
            self.readLoopThread = Thread(target=self.readLoop,args=())
            self.readLoopThread.start()
    
    def setLocals(self,locals):
        self.i2.locals.update(locals)
    
    def stopReadLoop(self, *args):
        self.running.clear()
        self.sendSigint()
        self.inputReady.set()
    
    def readLoop(self):
        self.running.set() # This Event triggers the gtk main loop to 
                           # start, which must happen before the 
                           # blocking write below can succeed.
        
        self.write('Robo Interacive Python Interpreter\n' +
                    sys.version + ' on ' + sys.platform + 
                    '\nType "help", "copyright", "credits" or "license" for more information.\n')
        self.prompt = self.ps1
        self.cursor = 0
        gobject.idle_add(self.setInteractiveLine,'')
        
        while self.running.isSet():
            try:
                self.inputWaiting.set()
                self.inputReady.wait()
                self.processInput()
            
            except KeyboardInterrupt:
                self.write('KeyboardInterrupt\n')
                with self.ipLock:
                    self.inputReady.clear()
                    self.inputPending = ''
                    self.interactiveLine = self.inputPending
                
                self.incomplete=[]
                self.prompt = self.ps1
                
                setEvt=Event()
                gobject.idle_add(self.setInteractiveLine,self.interactiveLine, setEvt)
                setEvt.wait()
            
            except Exception:
                traceback.print_exc()
    
    def processInput(self):
        with self.ipLock:
            input = None
            self.inputWaiting.clear()
            if self.inputReady.isSet():
                
                self.inputReady.clear()
                input = self.inputPending
                self.inputPending = ''
                
                if (not self.history or self.history[-1] != input.rstrip()) and input.rstrip():
                    self.history.append(input.rstrip())
                
                if self.historyIndex in self.historyModified:
                    self.historyModified.pop(self.historyIndex)
                self.historyIndex = len(self.history)
                
        if input != None and self.running.isSet():
            
            incomplete = self.executeInput(input)
                    
            if incomplete:
                self.incomplete.append(input)
                self.prompt = self.ps2
            else:
                self.incomplete=[]
                self.prompt = self.ps1
            
            with self.ipLock:
                if not self.inputPending.rstrip('\n'):
                    self.inputReady.clear()
                    self.inputPending=''
                
            setEvt=Event()
            gobject.idle_add(self.setInteractiveLine,self.interactiveLine,setEvt)
            setEvt.wait()
    
    def executeInput(self,input):
        
        command = ''.join(self.incomplete)+input
        
        if not command.strip():
            command = 'None'
        
        if (self.incomplete and
         input != '\n' and
        (self.incomplete[0].startswith('while') or 
         self.incomplete[0].startswith('for') or 
         self.incomplete[0].startswith('def') or
         self.incomplete[0].startswith('class'))):
            incomplete = True
        else:
            if self.getSource:
                source = self.getSource()
                sys.stdin = self
                sys.stdout = self
                sys.stderr = self
                try:
                    code = compile(source,'<code area>','exec')
                    self.i2.runcode(code)
                except SyntaxError as e:
                    self.i2.showsyntaxerror('<code area>')
            else:
                sys.stdin = self
                sys.stdout = self
                sys.stderr = self
            incomplete = self.i2.runsource(command,'<stdin>','single')
            sys.stderr = sys.__stderr__
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            self.EOF = False
        return incomplete
    
    def getCode(self,sourceReady):
        self.source = self.codeBuffer.get_text(*(self.codeBuffer.get_bounds()))
        sourceReady.set()
    
    def doEntry(self):
        with self.ipLock:
            self.interactiveLine += '\n'
            self.inputPending = self.interactiveLine
        
        self.cursor = 0
        self.cursorOn = True
        self.setInteractiveLine(self.interactiveLine)
        self.interactiveLine = ''
        self.prompt = ''
        self.inputReady.set()
    
    def keyCallback(self,widget,event,data=None):
        
        if event.string == '\r':
            self.doEntry()
            return True
        
        elif event.state & gtk.gdk.CONTROL_MASK:
            if(event.keyval == ord('c') or event.keyval == ord('C')):
                if event.state & gtk.gdk.SHIFT_MASK:
                    event.state &= ~gtk.gdk.SHIFT_MASK
                    return False
                else:
                    with self.ipLock:
                        self.interactiveLine += '^C\n'
                        self.inputPending = ''
                    self.setInteractiveLine(self.interactiveLine)
                    self.interactiveLine = ''
                    self.prompt = ''
                    self.sendSigint()
                    self.inputReady.set()
                    return True
            
            if(event.keyval == ord('d') or event.keyval == ord('D')):
                self.EOF = True
                self.doEntry()
                return True
            
            string=''
        
        elif event.keyval == 65362: # up
            with self.ipLock:
                if self.historyIndex > 0:
                    oldIndex = self.historyIndex
                    self.historyIndex -= 1
                    
                    if self.historyIndex in self.historyModified:
                        self.interactiveLine = self.historyModified[self.historyIndex]
                    else:
                        self.interactiveLine = self.history[self.historyIndex]
                    
                    self.cursor = len(self.interactiveLine)
                    self.cursorOn = True
                    # flow through to setInteractive line at the end of this block
                else:
                    return True
        
        elif event.keyval == 65364: # down
            with self.ipLock:
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
                    # flow through to setInteractive line at the end of this block
                else:
                    return True
        
        elif event.keyval == 65361: # left
            with self.ipLock:
                if self.cursor > 0:
                    self.cursor -= 1
                    self.cursorOn = True
                    self.updateCursor()
            return True
        
        elif event.keyval == 65363: # right
            with self.ipLock:
                if self.cursor < len(self.interactiveLine):
                    self.cursor += 1
                    self.cursorOn = True
                    self.updateCursor()
            return True
        
        elif event.keyval == 65288: #backspace
            with self.ipLock:
                if self.cursor > 0:
                    self.interactiveLine = self.interactiveLine[:self.cursor-1]+self.interactiveLine[self.cursor:]
                    self.cursor -= 1
                    if self.historyIndex < len(self.history):
                        self.historyModified[self.historyIndex] = self.interactiveLine
                    self.cursorOn = True
                    self.updateCursor()
                    # flow through to setInteractive line at the end of this block
                else:
                    return True
        
        elif event.keyval == 65289: #tab
            event.keyval = ord('\t')
            string = '\t'
        else:
            string = event.string
                
        if event.keyval < 256:
            with self.ipLock:
                self.interactiveLine = self.interactiveLine[:self.cursor] + string + self.interactiveLine[self.cursor:]
                self.cursor += len(string)
                if self.historyIndex < len(self.history):
                    self.historyModified[self.historyIndex] = self.interactiveLine
                else:
                    self.inputPending = self.interactiveLine
        
        self.setInteractiveLine(self.interactiveLine)
        
        return True
    
    def read(self,size=-1):
        
        if size == 0:
            return '\n'
        
        input = None
        self.inputWaiting.set()
        self.inputReady.wait()
        with self.ipLock:
            self.inputWaiting.clear()
            if self.inputReady.isSet():
                self.inputReady.clear()
                
                if size > 0:
                    input = self.inputPending[:size]
                    self.inputPending = self.inputPending[size:]
                else:
                    input = self.inputPending
                    self.inputPending = ''
        
        return input
    
    def readline(self,size=-1):
        return self.read(size)
    
    def readlines(self,sizehint=-1):
        lines=[]
        
        if sizehint < 0:
            sizehint = None
        
        while not self.EOF or (sizehint and len(lines) < sizehint):
            lines.append(self.readline())
        
        if lines[-1] == '\n':
            lines = lines[:-1]
        
        return lines
    
    def write(self,string):
        if self.guiThread == currentThread():
            self.insertEnd(string)
        else:
            writeEvt=Event()
            gobject.idle_add(self.insertEnd,string,writeEvt)
            writeEvt.wait()
    
    def flush():
        pass
    
    def insertEnd(self,string,writeEvt=None):
        with self.textLock:
            
            if self.pendingCR:
                string = '\r' + string
                
            if string.endswith('\r'):
                self.pendingCR = True
                string.rstrip('\r')
            else:
                self.pendingCR = False
            
            remaining = string
            elements = []
            while remaining:
                element,cr,remaining = remaining.partition('\r')
                if element:
                    elements.append(element)
                if cr and (not elements or elements[-1] != cr):
                    elements.append(cr)
            
            end = self.buffer.get_end_iter()
            iter = end.copy()
            iter.backward_char()
            self.buffer.delete(iter, end)
            
            for i in range(len(elements)):
                if elements[i] == '\r':
                    if elements[i+1][0] != '\n':
                        iter.set_line_offset(0)
                        end = self.buffer.get_end_iter()
                        self.buffer.delete(iter, end)
                else:
                    self.buffer.insert(iter,elements[i])
            
            lineStart = iter.copy()
            lineStart.set_line_offset(0)
            self.prompt = self.buffer.get_text(lineStart,iter)
            self.plen = len(self.prompt)
            self.cursor = 0;
            self.buffer.insert(iter,' ') # blank space for cursor at EOL
            
        self.updateCursor()
        if writeEvt:
            writeEvt.set()
        return False
    
    def scrollCallback(self,widget,data=None):
        if self.scrollToEnd:
            self.vadj.set_value(self.vadj.get_upper()-self.vadj.get_page_size())
        return False
    
    def setInteractiveLine(self,string,writeEvt=None):
        with self.textLock:
            bounds = self.buffer.get_selection_bounds()
            
            if bounds:
                marks = list(self.buffer.create_mark(None,i) for i in bounds)
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
            
            if bounds:
                bounds = tuple(self.buffer.get_iter_at_mark(m) for m in marks)
                self.buffer.select_range(*bounds)
            self.updateCursor(False)
        if writeEvt:
            writeEvt.set()
        return False
    
    def updateCursor(self, clear=True):
        
        if clear or not self.cursorOn:
            self.buffer.remove_all_tags(self.buffer.get_start_iter(), self.buffer.get_end_iter())
        
        if self.cursorOn:
            iter = self.buffer.get_end_iter()
            if iter.get_chars_in_line() > self.plen+self.cursor:
                iter.set_line_offset(self.plen+self.cursor)
                iter2 = self.buffer.get_end_iter()
                iter2.set_line_offset(self.plen+1+self.cursor)
                self.buffer.apply_tag_by_name('cursor',iter,iter2)
    
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
        
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_evt)
        self.window.set_title("Robo")
        self.window.set_size_request(800, 600)
        
        self.hpane = gtk.HPaned()
        
        self.vpane = gtk.VPaned()
        
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
        #self.codeTv.set_show_line_marks(True)
        self.codeTv.set_show_line_numbers(True)
        
        mono = pango.FontDescription('monospace 10')
        if mono:
            self.codeTv.modify_font(mono)
        
        environment = Environment()
        locals={'gui':self,'Gui':Gui, 'environment':environment, 'Robot':Robot}
        self.console = TvConsole(locals=locals, getSource=self.save_code)
        
        self.codeSw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.codeSw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.codeSw.add_with_viewport(self.codeTv)
        
#        self.codeSw = scintilla.Scintilla()
#        self.codeSw.SetLexerLanguage('python')
        
        try:
            code=self.load_code()
            self.codeTv.get_buffer().set_text(code)
        except IOError:
            pass
        except Exception as e:
            traceback.print_exc()
        
        self.graphics = gtk.DrawingArea()
        self.graphics.connect("configure_event", self.configure_graphics)
        self.graphics.connect("expose_event", self.push_graphics)
        
        self.canvas = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        self.canvas.widget = self.graphics.window
        environment.canvas = self.canvas
        self.drawing = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        environment.drawing = self.drawing
        self.background = gtk.gdk.Pixmap(self.graphics.window, 1, 1, depth=24)
        environment.background = self.background
        
        self.hpane.add1(self.vpane)
        self.vpane.add2(self.console.sw)
        self.hpane.add2(self.codeSw)
        
        self.vpane.add1(self.graphics)
        
        self.window.add(self.hpane)
        
        #self.graphics.set_size_request(500,400)
        #self.console.sw.set_size_request(500,200)
        #self.codeSw.set_size_request(300,600)
        self.console.sw.set_size_request(800,600)
        
        self.window.show_all()
    
    def save_code(self):
        b = self.codeTv.get_buffer()
        source = b.get_text(*(b.get_bounds()))
        f=open('source.py','w')
        f.write(source)
        f.close()
        return source
    
    def load_code(self,file='source.py'):
        f=open(file)
        text=f.read()
        f.close()
        return text
    
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
        self.console.running.wait() # console.readLoopThread must be set
                                    # correctly before proceeding.
        
        while self.console.readLoopThread.isAlive():
            try:
                with gtk.gdk.lock:
                    while gtk.events_pending():
                        gtk.main_iteration()
                    time.sleep(.001)
            except KeyboardInterrupt as e:
                pass


gui = None


def makeGui(guiReady=None, runGui=True):
    global gui
    gui = Gui()
    
    gui.console.guiThread=currentThread()
    
    if guiReady:
        guiReady.set()
    
    if runGui:
        gui.main()

def main(consoleMain=True):
        
    guiReady = Event()
    guiReady.clear()
    
    if not kernel32:
        gtk.gdk.threads_init()
    
    try:
        if consoleMain:
            Thread(target=makeGui,args=(guiReady,)).start()
        else:
            makeGui(guiReady, False)
        
        guiReady.wait() # gui thread must fully initialize console component
        gui.console.start(consoleMain)
        
        if not consoleMain:
            gui.main()
    
    except Exception as e:
        traceback.print_exc()
    except KeyboardInterrupt as e:
        traceback.print_exc()
    return gui

if __name__ == '__main__':
    main()
