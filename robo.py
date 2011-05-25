#!/usr/bin/env python

import sys, copy, time, os, traceback

from threading import Thread, Event, currentThread
from math import pi,atan2,sin,cos

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import pango
import cairo
import gtksourceview2

import gtkPythonConsole
gtkExec = gtkPythonConsole.gtkExec

if not os.getcwd() in sys.path:
    sys.path = [os.getcwd()] + sys.path


class Robot(object):
    def __init__(self,x=0,y=0,heading=0):
        global environment
        
        self.x = float(x)
        self.y = float(y)
        self.heading = heading
        self.xextent = 10
        self.yextent = 10
        self.gc = None
        self.penDown = False
        
        environment.robots.append(self)
        self.environment = environment
        
        self.lastDraw = self.drawingBoundingBox()
        self.lastX = self.x
        self.lastY = self.y
        self.queueRedraw()
    
    def pd(self):
        self.penDown = True
    
    def pu(self):
        self.penDown = False
    
    def getCanvas(self):
        return self.environment.canvas
    
    def getDrawing(self):
        return self.environment.drawing
    
    def queueRedraw(self):
        box1 = self.lastDraw
        box2 = self.drawingBoundingBox()
        if self.penDown:
            minx = min(box1[0],box2[0])
            miny = min(box1[1],box2[1])
            maxx = max(box1[0]+box1[2], box2[0]+box2[2])
            maxy = max(box1[1]+box1[3], box2[1]+box2[3])
            with gtk.gdk.lock:
                gtkExec(self.queue_gtk_draw,[(minx,miny, maxx-minx, maxy-miny)])
        else:
            gtkExec(self.queue_gtk_draw,[box1,box2])
    
    def queue_gtk_draw(self, boxes):
        try:
            for box in boxes:
                self.environment.graphics.queue_draw_area(*box)
        except:
            pass # probably there is no canvas to draw to right now
    
    def boundingBox(self):
        return self.x-self.xextent, self.y-self.yextent, 2*self.xextent, 2*self.yextent
    
    def drawingBoundingBox(self):
        canvas = self.getCanvas()
        w,h = canvas.get_width(),canvas.get_height()
        drawx, drawy = self.x+w/2.0, h/2.0-self.y
        x,y,width,height = (drawx-self.xextent, drawy-self.yextent,2*self.xextent,2*self.yextent)
        return int(round(x-1)),int(round(y-1)),int(round(width+2)),int(round(height+2))
    
    def redraw(self, canvas, x,y,ew,eh):
        w,h = canvas.get_width(),canvas.get_height()
        drawx, drawy = self.x+w/2.0, h/2.0-self.y
        if (((x < drawx+self.xextent) or (x+ew > drawx-self.xextent)) and
            ((y < drawy+self.yextent) or (y+eh > drawy-self.yextent))):
            if self.gc:
                gc = self.gc
            self.draw(canvas,x,y,ew,eh)
    
    def draw(self, canvas,ex,ey,ew,eh):
        w,h = canvas.get_width(),canvas.get_height()
        drawx, drawy = self.x+w/2.0, h/2.0-self.y
        drawLastX,drawLastY = self.lastX+w/2.0, h/2.0-self.lastY
        
        ctx = cairo.Context(canvas)
        ctx.set_line_width(1)
        
        ctx.arc(drawx,drawy,10,0,2*pi)
        ctx.set_source_rgba(1, 1, 1, 1)
        ctx.fill_preserve()
        
        ctx.move_to(drawx,drawy)
        ctx.rel_line_to(self.xextent*sin(self.heading*pi/180), -self.yextent*cos(self.heading*pi/180))
        
        ctx.set_source_rgba(0, 0, 0, 1)
        ctx.stroke()
        del(ctx)
        
        if self.penDown:
            ctx = cairo.Context(self.getDrawing())
            ctx.set_line_width(1)
            ctx.move_to(drawLastX,drawLastY)
            ctx.line_to(drawx, drawy)
            ctx.set_source_rgba(0, 0, 0, 1)
            ctx.stroke()
        
        self.lastDraw=self.drawingBoundingBox()
        self.lastX, self.lastY = self.x, self.y


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
        environment.graphics = self.graphics
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        environment.canvas = self.canvas
        self.drawing = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        environment.drawing = self.drawing
        self.background = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
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
        # called when graphics area is resized, not just created
        # TODO: resize canvas,drawing,background here instead of recreating
        x,y,w,h = widget.get_allocation()
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        environment.canvas = self.canvas
        self.drawing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        environment.drawing = self.drawing
        self.background = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        environment.background = self.background
        self.backBuffer = gtk.gdk.Pixmap(widget.window, w, h, depth=-1)
        environment.graphics = self.graphics
    
    def push_graphics(self,widget,event):
        
        x,y,w,h = event.area
        
        # TODO: clear canvas to transparent instead of re-creating it
        wx,wy,ww,wh = widget.get_allocation()
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, wh)
        environment.canvas = self.canvas
        for obj in environment.robots+environment.items:
            obj.redraw(self.canvas, x,y,w,h)
        
        # paint these to an offscreen pixmap and then swap buffers
        ctx = self.backBuffer.cairo_create()
        ctx.set_source_rgba(1, 1, 1, 1)
        ctx.paint()
        ctx.set_source_surface(self.background,0,0)
        ctx.paint()
        ctx.set_source_surface(self.drawing,0,0)
        ctx.paint()
        ctx.set_source_surface(self.canvas,0,0)
        ctx.paint()
        del(ctx)
        
        widget.window.draw_drawable(widget.get_style().fg_gc[gtk.STATE_NORMAL],self.backBuffer, x, y, x, y, w, h)
    
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
