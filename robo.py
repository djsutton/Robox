#!/usr/bin/env python

import sys, copy, time, os, traceback

from threading import Thread, Event, currentThread
from math import pi,atan2,sin,cos

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import pango
import gtksourceview2

import gtkPythonConsole
gtkExec = gtkPythonConsole.gtkExec

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
            with gtk.gdk.lock:
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
        
        self.codeArea = gtksourceview2.View(buffer)
        self.codeArea.set_indent_width(4)
        self.codeArea.set_tab_width(4)
        self.codeArea.set_insert_spaces_instead_of_tabs(True)
        self.codeArea.set_indent_on_tab(True)
        self.codeArea.set_highlight_current_line(True)
        self.codeArea.set_auto_indent(True)
        self.codeArea.set_show_line_numbers(True)
        
        mono = pango.FontDescription('monospace 10')
        if mono:
            self.codeArea.modify_font(mono)
        
        self.codeSw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.codeSw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.codeSw.add(self.codeArea)
        
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
        self.console = gtkPythonConsole.GtkPythonConsole(message='Robo Interacive Python Interpreter', locals=locals, getSource=self.get_code)
        
        self.consoleSw = gtk.ScrolledWindow(hadjustment=None, vadjustment=None)
        self.consoleSw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.consoleSw.add(self.console)
        
        self.hpane.add1(self.vpane)
        self.hpane.add2(self.codeSw)
        
        self.vpane.add1(self.graphics)
        self.vpane.add2(self.consoleSw)
        
        self.window.add(self.hpane)
        
        self.window.show_all()
        
        self.vpane.set_position(0)
        self.hpane.set_position(self.hpane.get_property('max-position'))
    
    def save_code(self,forceGrab=False):
        srcBuffer = self.codeArea.get_buffer()
        modified = srcBuffer.get_modified()
        if modified or forceGrab:
            source = srcBuffer.get_text(*srcBuffer.get_bounds())
            source = source.replace('\r\n','\n')
            
            if source and source[-1] != '\n':
                source += '\n'
            if modified:
                with open('source.py','wb') as f:
                    f.write(source)
                srcBuffer.set_modified(False)
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
            gtkExec(self.set_code, text, undoable)
    
    def set_code(self,code,undoable=True):
        srcBuffer = self.codeArea.get_buffer()
        
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
    
    if sys.platform != 'win32':
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
