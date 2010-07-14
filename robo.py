#!/usr/bin/env python

import code
import sys
import vte
import traceback
import pdb
import ctypes
import copy

from threading import Thread, Event, Lock, currentThread
from math import pi,atan2,sin,cos

sys.argv.append('--sync')

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import pango
import gtksourceview2
import scintilla

sys.argv.remove('--sync')

class Robot(object):
    def __init__(self,x=0,y=0,heading=0):
        print dir()
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
            self.environment.canvas.widget.queue_draw_area(*(self.lastDraw))
            self.environment.canvas.widget.queue_draw_area(*self.drawingBoundingBox())
        
    def boundingBox(self):
        return self.x-self.xextent, self.y-self.yextent,self.x+self.xextent,self.y+self.yextent
        
    def drawingBoundingBox(self):    
        x1,y1,x2,y2 = self.boundingBox()
        w,h = self.getCanvas().get_size()
        return x1+w/2,y1+h/2,x2+w/2,y2+h/2
    
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
        drawx,drawy=self.x+w/2,self.y+h/2
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
        self.inputPending = ''
        self.ipLock = Lock()
        self.interactiveLine = ''
        self.history = []
        self.historyIndex = 0
        self.historyModified = {}
        self.cursor = 0
        self.incomplete = []
        self.EOF=False
        
        self.tv = gtk.TextView(buffer=None)
        self.tv.set_wrap_mode(gtk.WRAP_WORD)
        self.tv.set_editable(False)
        
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
        
        self.pendingReturn = ''
        
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
        
        self.write('Robo Interacive Python Interpreter\n' +
                    sys.version + ' on ' + sys.platform + 
                    '\nType "help", "copyright", "credits" or "license" for more information.\n')
        
        self.prompt = sys.ps1
        self.write(self.prompt)
        gobject.idle_add(self.setInteractiveLine,'')
        self.running = True
        
        self.readLoopThread = Thread(target=self.readLoop,args=())
        self.readLoopThread.start()
    
    def setLocals(self,locals):
        self.i2.locals.update(locals)
    
    def readLoop(self):
        while self.running:
            try:
                input = None
                self.inputReady.wait()
                with self.ipLock:
                    if self.inputReady.isSet():
                        
                        self.inputReady.clear()
                        input = self.inputPending
                        self.inputPending = ''
                        self.interactiveLine = self.inputPending
                        self.cursor = 0
                        
                        if (not self.history or self.history[-1] != input.rstrip()) and input.rstrip():
                            self.history.append(input.rstrip())
                        
                        if self.historyIndex in self.historyModified:
                            self.historyModified.pop(self.historyIndex)
                        self.historyIndex = len(self.history)
                        
                if input != None:
                    incomplete = self.processInput(input)
                            
                    if incomplete:
                        self.incomplete.append(input)
                        self.prompt = sys.ps2
                    else:
                        self.incomplete=[]
                        self.prompt = sys.ps1
                    self.write(self.prompt)
                    gobject.idle_add(self.setInteractiveLine,self.interactiveLine)
            
            except KeyboardInterrupt:
                self.inputReady.clear()
                self.write('KeyboardInterrupt\n')
                self.incomplete=[]
                self.prompt = sys.ps1
                self.write(self.prompt)
                with self.ipLock:
                    self.inputPending = ''
                    self.interactiveLine = self.inputPending
                gobject.idle_add(self.setInteractiveLine,self.interactiveLine)
            except Exception:
                traceback.print_exc()
            
    def processInput(self,input):
        
        command = ''.join(self.incomplete)+input
        
        if not command.strip():
            command = 'None'
        
        #print list(ord(c) for c in input)
        
        if (self.incomplete and
         input != '\n' and
        (self.incomplete[0].startswith('while') or 
         self.incomplete[0].startswith('for') or 
         self.incomplete[0].startswith('def') or
         self.incomplete[0].startswith('class'))):
            incomplete = True
        else:
            sys.stdin = self
            sys.stdout = self
            sys.stderr = self
            if self.getSource:
                source = self.getSource()
                try:
                    code = compile(source,'<code area>','exec')
                    self.i2.runcode(code)
                except SyntaxError as e:
                    print e
                    self.i2.showsyntaxerror('<code area>')
            incomplete = self.i2.runsource(command,'<console>','single')
            sys.stderr = sys.__stderr__
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
        return incomplete
    
    def getCode(self,sourceReady):
        self.source = self.codeBuffer.get_text(*(self.codeBuffer.get_bounds()))
        sourceReady.set()
    
    def keyCallback(self,widget,event,data=None):
        #stdout = sys.stdout
        #sys.stdout = sys.__stdout__
        #print dir(event)
        #print 'ctrl:',bool(event.state & gtk.gdk.CONTROL_MASK)
        #print 'shift:',bool(event.state & gtk.gdk.SHIFT_MASK)
        #print event.keyval, list(ord(c) for c in event.string), "'"+event.string+"'"
        #sys.stdout = stdout
        #inputReady = False
        
        if event.string == '\r':
            with self.ipLock:
                self.interactiveLine += '\n'
                self.inputPending = self.interactiveLine
            self.inputReady.set()
        
        elif event.state & gtk.gdk.CONTROL_MASK:
            if(event.keyval == ord('c') or event.keyval == ord('C')):
                if event.state & gtk.gdk.SHIFT_MASK:
                    event.state &= ~gtk.gdk.SHIFT_MASK
                    return False
                else:
                    with self.ipLock:
                        self.interactiveLine += '\n'
                        self.inputPending = self.interactiveLine
                    self.setInteractiveLine(self.interactiveLine)
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(self.readLoopThread.ident, ctypes.py_object(KeyboardInterrupt))
                    self.inputReady.set()
                    return True
            string=''
        
        elif event.keyval == 65362: # up
            with self.ipLock:
                oldIndex = self.historyIndex
                self.historyIndex -= 1
                if self.historyIndex < 0:
                    self.historyIndex = 0
                if self.historyIndex < len(self.history):
                    if self.historyIndex in self.historyModified:
                        self.interactiveLine = self.historyModified[self.historyIndex]
                    else:
                        self.interactiveLine = self.history[self.historyIndex]
                if oldIndex != self.historyIndex:
                    self.cursor = len(self.interactiveLine)
            
        elif event.keyval == 65364: # down
            with self.ipLock:
                oldIndex = self.historyIndex
                self.historyIndex += 1
                if self.historyIndex > len(self.history):
                    self.historyIndex = len(self.history)
                if self.historyIndex < len(self.history):
                    if self.historyIndex in self.historyModified:
                        self.interactiveLine = self.historyModified[self.historyIndex]
                    else:
                        self.interactiveLine = self.history[self.historyIndex]
                else:
                    self.interactiveLine = self.inputPending
                if oldIndex != self.historyIndex:
                    self.cursor = len(self.interactiveLine)
                
                
        elif event.keyval == 65361: # left
            with self.ipLock:
                self.cursor -= 1
                if self.cursor < 0:
                    self.cursor = 0
        elif event.keyval == 65363: # right
            with self.ipLock:
                self.cursor += 1
                if self.cursor > len(self.interactiveLine):
                    self.cursor = len(self.interactiveLine)
        elif event.keyval == 65288: #backspace
            with self.ipLock:
                if self.cursor > 0:
                    self.interactiveLine = self.interactiveLine[:self.cursor-1]+self.interactiveLine[self.cursor:]
                    self.cursor -= 1
                    if self.historyIndex < len(self.history):
                        self.historyModified[self.historyIndex] = self.interactiveLine
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
        
        event = Event()
        gobject.idle_add(event.set)
        event.wait()
        
        gobject.idle_add(self.setInteractiveLine,self.interactiveLine)
        
        iter = self.buffer.get_end_iter()
        iter.set_line_offset(0)
        end = self.buffer.get_end_iter()
        
        self.prompt = self.buffer.get_text(iter,end)
        
        #stdout = sys.stdout
        #sys.stdout = sys.__stdout__
        #print 'prompt is:', self.prompt
        #sys.stdout = stdout
        
        input = None
        self.inputReady.wait()
        with self.ipLock:
            if self.inputReady.isSet():
                self.inputReady.clear()
                
                if size > 0:
                    input = self.inputPending[:size]
                    self.inputPending = self.inputPending[size:]
                else:
                    input = self.inputPending
                    self.inputPending = ''
                self.interactiveLine = self.inputPending
        
        #stdout = sys.stdout
        #sys.stdout = sys.__stdout__
        #print 'inputPending is:', self.inputPending
        #sys.stdout = stdout
        
        return input
    
    def readline(self,size=-1):
        return self.read(size)
    
    def readlines(self,sizehint=-1):
        lines=[]
        
        if sizehint < 0:
            sizehint = None
        
        while not self.EOF or (sizehint and len(lines) < sizehint):
            lines.append(self.readline())
        return lines
        
    def write(self,string):
        #sys.__stdout__.write('write: ' + string + '\n')
        gobject.idle_add(self.insertEnd,string)
    
    def flush():
        pass
    
    def insertEnd(self,string):
        with self.textLock:
            
            if self.pendingReturn:
                string = '\r' + string
                
            if string.endswith('\r'):
                self.pendingReturn = '\r'
                string.rstrip('\r')
            else:
                self.pendingReturn = ''
            
            remaining = string
            elements = []
            while remaining:
                element,cr,remaining = remaining.partition('\r')
                if element:
                    elements.append(element)
                if cr and (not elements or elements[-1] != cr):
                    elements.append(cr)
            
            
            #stdout = sys.stdout
            #sys.stdout = sys.__stdout__
            #print elements
            #sys.stdout = stdout
            
            for i in range(len(elements)):
                iter = self.buffer.get_end_iter()
                if elements[i] == '\r':
                    if elements[i+1][0] != '\n':
                        iter.set_line_offset(0)
                        end = self.buffer.get_end_iter()
                        self.buffer.delete(iter, end)
                else:
                    self.buffer.insert(iter,elements[i])
            
            
    
    def scrollCallback(self,widget,data=None):
        if self.scrollToEnd:
            self.vadj.set_value(self.vadj.get_upper()-self.vadj.get_page_size())
        return False
    
    def setInteractiveLine(self,string):
        with self.textLock:
            bounds = self.buffer.get_selection_bounds()
            plen = len(self.prompt)
            if bounds:
                marks = list(self.buffer.create_mark(None,i) for i in bounds)
            end = self.buffer.get_end_iter()
            iter = self.buffer.get_end_iter()
            if iter.get_chars_in_line() > plen:
                iter.set_line_offset(plen)
            self.buffer.delete(iter, end)
            end = self.buffer.get_end_iter()
            if string.endswith('\n'):
                self.buffer.insert(end,string)
            else:
                self.buffer.insert(end,string+' ')
            if bounds:
                bounds = tuple(self.buffer.get_iter_at_mark(m) for m in marks)
                self.buffer.select_range(*bounds)
            iter = self.buffer.get_end_iter()
            if iter.get_chars_in_line() > plen+self.cursor:
                iter.set_line_offset(plen+self.cursor)
                iter2 = self.buffer.get_end_iter()
                iter2.set_line_offset(plen+1+self.cursor)
                self.buffer.apply_tag_by_name('cursor',iter,iter2)
            
    def call(self,(function,args)):
        function(*args)
        
class Gui(object):
    def delete_evt(self,widget,event,data=None):
        # False -> destroy window
        # True -> dont destroy window
        return False
        
    def destroy_sig(self,widget,data=None):
        gtk.main_quit()
        
    def __init__(self):
        global environment
        
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("destroy", self.destroy_sig)
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
        except Exception as e:
            traceback.print_exc()
        
        self.graphics = gtk.DrawingArea()
        self.graphics.connect("configure_event", self.configure_graphics)
        self.graphics.connect("expose_event", self.push_graphics)
        
        self.hpane.add1(self.vpane)
        self.vpane.add2(self.console.sw)
        self.hpane.add2(self.codeSw)
        
        self.vpane.add1(self.graphics)
        
        self.window.add(self.hpane)
        
        #self.graphics.set_size_request(500,400)
        #self.console.sw.set_size_request(500,200)
        #self.codeSw.set_size_request(300,600)
        self.console.sw.set_size_request(800,600)
        
        for obj in [self.graphics,self.console.tv,self.console.sw,self.codeTv,self.codeSw,self.vpane,self.hpane,self.window]:
            obj.show()
        
        gtk.gdk.threads_init()
        
        #colormap = self.canvas.get_colormap()

        #white = colormap.alloc_color('white')
        #black = colormap.alloc_color('black')
        
        #self.gc = self.canvas.new_gc()
        #self.gc.set_background(white)
        #self.gc.set_foreground(white)
        #self.canvas.draw_rectangle(self.gc, True,0,0,20,20)
        #self.gc.set_foreground(black)
        
#        Thread(target=self.main,args=()).start()
    def save_code(self):
        b = self.codeTv.get_buffer()
        source = b.get_text(*(b.get_bounds()))
        f=open('code.py','w')
        f.write(source)
        return source
    def load_code(self,file='code.py'):
        f=open(file)
        return f.read()
        
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
#        self.canvas.draw_line(widget.get_style().black_gc,-10,-20,50,100)
        for obj in environment.robots+environment.items:
            obj.redraw(self.canvas, widget.get_style().black_gc, x,y,w,h)
        widget.window.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],self.canvas, x, y, x, y, w, h)
        return False
        
    def main(self):
        gtk.main()

    

if __name__ == '__main__':
    gui = Gui()
    gui.main()
