#!/usr/bin/env python

import sys, copy, time, os, traceback

from threading import Thread, Event, currentThread
from math import pi,atan2,sin,cos,fabs

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import pango
import cairo
import gtksourceview2

import gtkPythonConsole
gtkPythonConsole.ExceptionHideFiles.append(__file__)
gtkExec = gtkPythonConsole.gtkExec

if not os.getcwd() in sys.path:
    sys.path = [os.getcwd()] + sys.path

environment = None

class Robot(object):
    def __init__(self, x=0, y=0, heading=0, env = None):
        global environment
        
        object.__setattr__(self,'x',float(x))
        object.__setattr__(self,'y',float(y))
        object.__setattr__(self,'heading',float(heading))
        object.__setattr__(self,'size',10.0)
        self.xextent = self.size*1.05
        self.yextent = self.size*1.05
        self.penDown = False
        object.__setattr__(self,'paths',[])
        self.drawing = None
        self.auto_draw = True
        
        if env == None:
            env = environment
        
        self.environment = env
        self.environment.robots.append(self)
        
        self.doodle = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0))
        
        self.lastDraw = self.drawingBoundingBox()
        self.lastX = x
        self.lastY = y
        self.pose = x, y, heading
        self.sep_path_layer=True
    
    def remove(self):
        try:
            self.environment.robots.remove(self)
        except ValueError:
            raise ValueError('Robot not found in environment')
        
        gtkExec(self.queue_gtk_draw) # redraw entire area TODO: limit this to path area + robot area
    
    def __setattr__(self, name, value):
        
        if name == 'x' or name == 'y' or name == 'size':
            value = float(value)
        elif name == 'heading':
            value = float(value)%360
        elif name == 'point':
            x,y = value
            value = float(x), float(y)
        elif name == 'pose':
            x,y,heading = value
            value = float(x), float(y), float(heading)%360
        elif name == 'paths':
            if type(value) != list:
                value == list(value)
        
        object.__setattr__(self, name, value)
        
        if name == 'x' or name == 'y':
            object.__setattr__(self, 'point', (self.x, self.y))
            object.__setattr__(self, 'pose', (self.x, self.y, self.heading))
            self.updateGraphics()
        elif name == 'heading':
            object.__setattr__(self, 'pose', (self.x, self.y, self.heading))
            self.updateGraphics()
        elif name == 'point':
            x,y = value
            object.__setattr__(self, 'x', x)
            object.__setattr__(self, 'y', y)
            object.__setattr__(self, 'pose', (x, y, self.heading))
            self.updateGraphics()
        elif name == 'pose':
            x,y,heading = value
            object.__setattr__(self, 'x', x)
            object.__setattr__(self, 'y', y)
            object.__setattr__(self, 'point', (x, y))
            object.__setattr__(self, 'heading', heading)
            self.updateGraphics()
        elif name == 'paths':
            if value == [] and self.penDown:
                self.pu()
                self.pd()
            gtkExec(self.queue_gtk_draw) # redraw entire area
        elif name == 'size':
            self.xextent = value*1.05
            self.yextent = value*1.05
            self.updateGraphics()
    
    def pd(self):
        if not self.penDown:
            self.penDown = True
            
            path = Path(self.x, self.y)
            self.paths.append(path)
    
    def pu(self):
        if self.penDown:
            self.penDown = False
    
    def fd(self, distance):
        dist = float(distance)
        self.point = self.x+dist*sin(self.heading*pi/180.0), self.y+dist*cos(self.heading*pi/180.0)
    
    def bk(self, distance):
        self.fd(-distance)
    
    def rt(self, degrees):
        self.heading += float(degrees)
    
    def lt(self, degrees):
        self.heading -= float(degrees)
    
    def cg(self, zero=False):
        pen = False
        if self.penDown:
            pen = True
            self.pu()
        self.paths=[]
        
        if zero:
            self.pose=(0,0,0)
        
        if pen:
            self.pd()
        
        gtkExec(self.queue_gtk_draw) # redraw entire area
    
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
            gtkExec(self.queue_gtk_draw,[(minx,miny, maxx-minx, maxy-miny)])
        else:
            gtkExec(self.queue_gtk_draw,[box1,box2])
    
    def queue_gtk_draw(self, boxes=None):
        if boxes:
            for box in boxes:
                self.environment.graphics.queue_draw_area(*box)
        else:
            self.environment.graphics.queue_draw()
    
    def boundingBox(self):
        return self.x-self.xextent, self.y-self.yextent, 2*self.xextent, 2*self.yextent
    
    def drawingBoundingBox(self):
        canvas = self.getCanvas()
        w,h = canvas.get_width(),canvas.get_height()
        drawx, drawy = self.x+w/2.0, h/2.0-self.y
        maxExtent = max(self.xextent, self.yextent)
        x,y,size = (drawx-maxExtent, drawy-maxExtent,2*maxExtent)
        intSize = int(round(size+2))+20
        return int(round(x-1))-10,int(round(y-1))-10,intSize,intSize
    
    def redraw(self, (canvas,drawing), x,y,ew,eh):
        w,h = canvas.get_width(),canvas.get_height()
        drawx, drawy = self.x+w/2.0, h/2.0-self.y
        if (((x < drawx+self.xextent) or (x+ew > drawx-self.xextent)) and
            ((y < drawy+self.yextent) or (y+eh > drawy-self.yextent))):
            self.render((canvas,drawing),x,y,ew,eh)
    
    def render(self, (canvas,drawing),ex,ey,ew,eh):
        w,h = canvas.get_width(),canvas.get_height()
        cx, cy = w/2.0, h/2.0
        drawx, drawy = self.x+cx, cy-self.y
        drawLastX,drawLastY = self.lastX+cx, cy-self.lastY
        
        ctx = cairo.Context(canvas)
        ctx.set_line_width(1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        
        ctx.save()
        
        ctx.translate(drawx,drawy)
        ctx.rotate(self.heading*pi/180)
        ctx.scale(self.size,-self.size)
        ctx.save()
        
        self.draw(ctx)
        
        ctx.restore()
        ctx.restore()
        
        if self.paths:
            if self.sep_path_layer:
                ctx = cairo.Context(drawing)
            
            for path in self.paths:
                ctx.save()
                path.draw(ctx, cx, cy, w, h)
                ctx.restore()
        
        self.lastDraw=self.drawingBoundingBox()
    
    def draw(self,ctx):
        
        ctx.arc(0,0,1,0,2*pi)
        ctx.set_source_rgba(1, 1, 1, 1)
        ctx.fill_preserve()
        
        ctx.move_to(0,0)
        ctx.rel_line_to(0, 1)
        
        ctx.set_source_rgba(0,0,0,1)
        ctx.set_line_width(.1)
        ctx.stroke()
    
    def updateGraphics(self):
        if self.paths and self.penDown:
            
            self.paths[-1].add(self.x, self.y)
        
        self.lastX, self.lastY = self.x, self.y
        
        if self.auto_draw:
            self.queueRedraw()


class Path(object):
    def __init__(self, x, y):
        self.points=[(x,y)]
        
        self.pathCtx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0))
        self.pathCtx.move_to(x,y)
        
        self.path = self.pathCtx.copy_path()
    
    def add(self, x, y):
        if (x,y) != self.points[-1]:
            self.points.append((x,y))
            
            self.pathCtx.line_to(x,y)
            self.path = self.pathCtx.copy_path()
    
    def draw(self, ctx, zeroX, zeroY, canvasW, canvasH):
        ctx.set_line_width(1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        
        ctx.translate(zeroX, zeroY)
        ctx.scale(1,-1)
        
        ctx.new_path()
        ctx.append_path(self.path)
        
        ctx.set_source_rgba(0, 0, 0, 1)
        ctx.stroke()


class Environment(object):
    def __init__(self):
        self.robots=[]
        self.items=[]
        self.background = None
    
    def cg(self):
        for r in self.robots:
            r.cg()
    
    def globalized_vars(self):
        return {'cg': self.cg}


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
        self.window.set_title('Robox')
        self.window.set_default_size(800, 600)
        
        self.hpane = gtk.HPaned()
        self.hpane.proportion=0
        self.hpane.width=0
        self.hpane.update = True
        #self.hpane.connect('expose-event', self.expose_pane)
        #self.hpane.positionHandler = self.hpane.connect('notify::position', self.reposition_pane)
        
        self.vpane = gtk.VPaned()
        self.vpane.proportion=0
        self.vpane.height=0
        self.vpane.update = True
        #self.vpane.connect('expose-event', self.expose_pane)
        #self.vpane.positionHandler = self.vpane.connect('notify::position', self.reposition_pane)
        
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
        
        self.codeModified = True
        
        self.graphics = gtk.DrawingArea()
        self.graphics.set_can_focus(True)
        self.graphics.connect("configure-event", self.configure_graphics)
        self.graphics.connect("expose-event", self.push_graphics)
        self.graphics.connect('key-press-event',self.graphics_key_press)
        self.graphics.connect('key-release-event',self.graphics_key_release)
        self.graphics.connect('button-press-event',self.graphics_button_press)
        self.graphics.connect('button-release-event',self.graphics_button_release)
        self.graphics.connect('motion_notify_event', self.graphics_mouse_motion)
        
#        self.readcharLock = RLock() # lock related to readchar processing
        
        self.graphics.add_events(gtk.gdk.EXPOSURE_MASK
                               | gtk.gdk.KEY_PRESS_MASK  
                               | gtk.gdk.KEY_RELEASE_MASK
                               | gtk.gdk.BUTTON_PRESS_MASK  
                               | gtk.gdk.BUTTON_RELEASE_MASK
                               | gtk.gdk.POINTER_MOTION_MASK
                               | gtk.gdk.POINTER_MOTION_HINT_MASK)
        
        self.resize_handlers = []
        self.key_press_handlers = []
        self.key_release_handlers = []
        self.button_press_handlers = []
        self.button_release_handlers = []
        self.mouse_move_handlers = []
        
        self.environment = Environment()
        self.environment.graphics = self.graphics
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        self.environment.canvas = self.canvas
        self.drawing = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        self.environment.drawing = self.drawing
        self.background = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        self.environment.background = self.background
        environment = self.environment
        
        local_vars={'gui':self, 'Gui':Gui, 'environment':self.environment, 'Robot':Robot, 'gtkExec':gtkExec}
        local_vars.update(environment.globalized_vars())
        self.console = gtkPythonConsole.GtkPythonConsole(message='Robox Interacive Python Interpreter', locals=local_vars, getSource=self.get_code)
        
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
    
    def save_code(self,forceGrab=False,filename='source.py'):
        srcBuffer = self.codeArea.get_buffer()
        modified = srcBuffer.get_modified()
        if modified or forceGrab:
            source = srcBuffer.get_text(*srcBuffer.get_bounds())
            source = source.replace('\r\n','\n')
            
            if source and source[-1] != '\n':
                source += '\n'
            if modified:
                with open(filename,'wb') as f:
                    f.write(source)
                srcBuffer.set_modified(False)
        else:
            source=None
        
        return source
    
    def get_code(self):
        source = self.save_code(self.codeModified, self.filename)
        self.codeModified = False
        return source
    
    def load_code(self,filename='source.py',undoable=True):
        self.filename = filename
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
        self.codeModified = True
        
        if not undoable:
            srcBuffer.end_not_undoable_action()
        self.window.set_title('Robox  -  %s'%self.filename)
    
    def on_key_press(self,func):
        if func not in self.key_press_handlers:
            self.key_press_handlers.append(func)
    
    def on_key_release(self,func):
        if func not in self.key_release_handlers:
            self.key_release_handlers.append(func)
    
    def on_button_press(self,func):
        if func not in self.button_press_handlers:
            self.button_press_handlers.append(func)
    
    def on_button_release(self,func):
        if func not in self.button_release_handlers:
            self.button_release_handlers.append(func)
    
    def on_mouse_move(self,func):
        if func not in self.mouse_move_handlers:
            self.mouse_move_handlers.append(func)
    
    def on_resize(self,func):
        if func not in self.resize_handlers:
            self.resize_handlers.append(func)
    
    def on_timer(self,func,miliseconds,*args,**kwargs):
        gobject.timeout_add(miliseconds,func,*args,**kwargs)
    
    def readchar(self):
        char = 0 #get keyval here
        if char < 127:
            char = chr(char)
        return char
    
    def redraw(self):
        gtkExec(self.graphics.queue_draw)
    
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
    
    def graphics_key_press(self, widget, event, data=None):
        for func in self.key_press_handlers:
            func(event)
        return True
    
    def graphics_key_release(self, widget, event, data=None):
        for func in self.key_release_handlers:
            func(event)
        return True
    
    def graphics_button_press(self, widget, event, data=None):
        widget.grab_focus()
        _,_,w,h = self.graphics.get_allocation()
        x = event.x - w/2.0
        y = h/2.0 - event.y 
        for func in self.button_press_handlers:
            func(x,y,event.button)
        return True
        
    def graphics_button_release(self, widget, event, data=None):
        _,_,w,h = self.graphics.get_allocation()
        x = event.x - w/2.0
        y = h/2.0 - event.y 
        for func in self.button_release_handlers:
            func(x,y,event.button)
        return True
    
    def graphics_mouse_motion(self, widget, event, data=None):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x
            y = event.y
            state = event.state
        for func in self.mouse_move_handlers:
            func((x,y,state))
        return True
    
    def configure_graphics(self, widget, event):
        # called when graphics area is resized, not just created
        # TODO: resize canvas,drawing,background here instead of recreating
        x,y,w,h = widget.get_allocation()
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        self.environment.canvas = self.canvas
        self.drawing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        self.environment.drawing = self.drawing
        if self.background:
            if (w > self.background.get_width() or h > self.background.get_height()):
                old = self.background
                self.background = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(w,old.get_width()), max(h,old.get_height()))
                ctx = cairo.Context(self.background)
                ctx.set_source_surface(old,0,0)
                ctx.paint()
        else:
            self.background = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        self.environment.background = self.background
        self.backBuffer = gtk.gdk.Pixmap(widget.window, w, h, depth=-1)
        self.environment.graphics = self.graphics
        
        for func in self.resize_handlers:
            func((w,h),widget,event)
    
    def push_graphics(self,widget,event):
        
        x,y,w,h = event.area
        
        # TODO: clear canvas to transparent instead of re-creating it
        wx,wy,ww,wh = widget.get_allocation()
        self.canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, wh)
        self.environment.canvas = self.canvas
        self.drawing = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, wh)
        self.environment.drawing = self.drawing
        for obj in self.environment.robots+self.environment.items:
            obj.redraw((self.canvas,self.drawing), x,y,w,h)
        
        # paint these to an offscreen pixmap and then swap buffers
        ctx = self.backBuffer.cairo_create()
        ctx.set_source_rgba(1, 1, 1, 1) #clear to white
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
    
    filename = None;
    
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    
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
        
        if filename:
            gui.load_code(filename, undoable=False)
        else:
            gui.load_code(undoable=False)
        
        if gui:
            gui.console.start(consoleMain)
        
            if not consoleMain:
                gui.main()
    
    except Exception as e:
        traceback.print_exc(file=sys.__stdout__)
    return gui

if __name__ == '__main__':
    main()
