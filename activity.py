# -*- coding: UTF-8 -*-
# Copyright 2007-2008 One Laptop Per Child
# Copyright 2007 Gerard J. Cerchio <www.circlesoft.com>
# Copyright 2008 Andrés Ambrois <andresambrois@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import logging
import sugar.logger

from gettext import gettext as _

import cPickle
import gtk
from sugar.activity.activity import Activity, ActivityToolbox

from gametoolbar import GameToolbar
from gogame import GoGame
import boardwidget
import infopanel
from collaboration import CollaborationWrapper


logger = logging.getLogger('PlayGo')

DEFAULT_SIZE = 19

class PlayGo(Activity):
    def __init__(self, handle):
        # Initialize the parent
        Activity.__init__(self, handle)
        logger.debug('Initiating PlayGo')
        
        self.size = DEFAULT_SIZE
        
        # Set the activity toolbox
        toolbox = ActivityToolbox(self)
        self.set_toolbox(toolbox)
        self.gameToolbar = GameToolbar(self)
        toolbox.add_toolbar(_('Game'), self.gameToolbar)
        self.gameToolbar.connect('game-restart', self.restart_game)
        self.gameToolbar.connect('game-board-size', self.board_size_change)
        self.gameToolbar.show()  
        
        # Initialize the game
        self.game = GoGame(self.size)
        self.CurrentColor = 'B'
        self.PlayerColor = 'B'
        self.set_up_ui()
        
        if not handle.object_id:
            self.infopanel.show(_('Welcome to PlayGo!'))
        else:
            self.show_score()
        self.lastX = -1
        self.lastY = -1
            
        #Set up collaboration
        self.collaboration = CollaborationWrapper(self, 
                                                  self.buddy_joined, 
                                                  self.buddy_left, 
                                                  self.Play, 
                                                  self.game.undostack, 
                                                  self.bootstrap)
        
        self.connect('shared', self.collaboration._shared_cb)
        if self._shared_activity:
            # We are joining the activity
            self.connect('joined', self.collaboration._joined_cb)
            if self.get_shared():
                # We've already joined
                self.collaboration._joined_cb()

    def set_up_ui(self):        
        self.board = boardwidget.GoBoardWidget(self.game.get_status(), self.size)
        self.board.connect('motion-notify-event', self.board_motion_cb)
        self.board.connect('insert-requested', self.insert_cb)
        
        self.main_view = gtk.VBox()
        
        self.board_aspect = gtk.AspectFrame(None, .5, .5, 1, False)
        self.board_aspect.add(self.board)
        self.main_view.pack_start(self.board_aspect)
        
        self.buttons_box = gtk.HBox()
        self.buttons_alignment = gtk.Alignment(0.5, 1, 0.5, 1)
        #Pass button
        self.pass_button = gtk.Button(_('Pass'))
        self.pass_button.connect("clicked",  self.pass_cb)
        self.buttons_box.pack_start(self.pass_button,  True,  True, 10)
        
        #Undo button
        self.undo_button = gtk.Button(_('Undo'))
        self.undo_button.connect("clicked",  self.undo_cb)
        self.buttons_box.pack_start(self.undo_button, True, True, 10)
        
        self.buttons_alignment.add(self.buttons_box)
        self.main_view.pack_start(self.buttons_alignment, False, padding=10)
        
        self.infopanel = infopanel.InfoPanel()
        self.main_view.pack_start(self.infopanel, False)

        self.set_canvas(self.main_view)
        self.show_all()

    def insert_cb(self, widget, x, y, announce=True):
        if announce and self.get_currentcolor() != self.get_playercolor():
            logger.debug('Play at %s x %s was out-of-turn!', x, y)
            self.infopanel.show('It\'s not your turn!')
            return False
        # Make the play only if it wasn't a pass move. 
        if x != -1:
            error = self.game.illegal(x, y, self.get_currentcolor())
            if error:
                self.infopanel.show(error)
                return False
            # Make the play
            captures = self.game.play((x, y), self.get_currentcolor())
            self.gameToolbar.grey_out_size_change()
            if captures: self.redraw_captures(captures)
            self.show_score()
            self.board.draw_stone(x, y, self.get_currentcolor(), widget)
        # Announce the local play
        if self.get_shared() and announce:
            self.collaboration.Play(x, y)
        self.change_turn()
        if not self.get_shared(): self.change_player_color()

    def undo_cb(self, widget, data=None):
        if self.game.undo():
            self.board.queue_draw()
            self.change_turn()
            if not self.get_shared(): self.change_player_color()
        
    def pass_cb(self, widget, data=None):
        if self.get_shared(): 
            if self.get_currentcolor() == self.get_playercolor():
                self.collaboration.Play(-1, -1)
            else:
                self.infopanel.show('It\'s not your turn!')
                return
        else:
            self.change_player_color()
        self.change_turn()

    def write_file(self, file_path):
        logger.debug('Writing file: %s', file_path)
        # Strip the undostack
        undostack = self.game.undostack[:]
        strippedstack = []
        for pos, color, captures in undostack:
            strippedstack.append(pos)
        f = open(file_path, 'w')
        try:
            cPickle.dump(strippedstack, f, cPickle.HIGHEST_PROTOCOL)
        finally:
            f.close()
        self.metadata['our-color'] = self.get_playercolor()
        self.metadata['shared'] = str(self.get_shared())
        self.metadata['size'] = str(self.size)
        
    def read_file(self, file_path):
        logger.debug('Reading file: %s', file_path)
        f = open(file_path, 'r')
        try:
            newstack = cPickle.load(f)
        finally:
            f.close()
        if self.get_shared():
            logger.debug('The game we are loading is shared!')
            self.PlayerColor = self.metadata.get('our-color', 'B')
        if self.size != self.metadata.get('size', DEFAULT_SIZE):
            self.board_size_change(None, int(self.metadata.get('size', DEFAULT_SIZE)))
        self.bootstrap(newstack)
        
    def board_motion_cb(self, widget, event):
        x, y = self.board.get_mouse_event_xy(event)
        if x == self.lastX and y == self.lastY:
            return
        self.lastX = x
        self.lastY = y
        if not self.game.is_occupied(x, y) and self.game.legal((x, y), self.get_playercolor()):
            self.board.draw_ghost_stone(x, y, self.get_playercolor())
    
    def invert_color(self, color):
        if color == 'B': return 'W'
        return 'B'
    
    def get_currentcolor(self):
        return self.CurrentColor
    
    def change_turn(self):
        # It's the other guy's turn now
        if self.CurrentColor == 'B':
            self.infopanel.show('White\'s turn')
        else:
            self.infopanel.show('Black\'s turn')
        self.CurrentColor = self.invert_color(self.get_currentcolor())

    def get_playercolor(self):
        return self.PlayerColor

    def change_player_color(self):
        self.PlayerColor = self.invert_color(self.get_playercolor())
        
    def set_player_color(self, color):
        self.PlayerColor = color

    def redraw_captures(self, captures):
        for x in captures:
            self.board.redraw_area(x[0], x[1])
            
    def bootstrap(self, plays):
        ''' Take our game to the state it would have if @plays were manually played'''
        logger.debug('Bootstraping...')
        self.board.do_expose_event() # HACK: Looks like read_file is called before the board is exposed
        for pos in plays:
            logger.debug('Playing at %s with color %s', pos, self.get_currentcolor())
            captures = self.game.play((pos[0], pos[1]), self.get_currentcolor())
            if captures: self.redraw_captures(captures)
            self.change_turn()
            self.change_player_color()
        logger.debug('Color after bootstraping is %s', self.get_currentcolor())
        self.show_score()
        self.board.do_expose_event()
        
    def restart_game(self, widget=None):
        logger.debug('Received restart signal!')
        self.game.clear()
        self.board.status = self.game.status
        self.board.do_expose_event()
        self.show_score()
        
    def board_size_change(self, widget, size):
        if size == self.size:
            return
        self.size = size
        del self.game
        self.game = GoGame(size)
        self.board_aspect.remove(self.board)
        del self.board
        self.board = boardwidget.GoBoardWidget(self.game.get_status(), int(size))
        self.board_aspect.add(self.board)
        self.board.connect('motion-notify-event', self.board_motion_cb)
        self.board.connect('insert-requested', self.insert_cb)
        self.board.show()
        
    def show_score(self):
        self.infopanel.show_score(_("Score is: Whites %(W)d - Blacks %(B)d" % self.game.get_score()))
    
    def _alert(self, title, text=None):
        from sugar.graphics.alert import NotifyAlert
        alert = NotifyAlert(timeout=5)
        alert.props.title = title
        alert.props.msg = text
        self.add_alert(alert)
        alert.connect('response', self._alert_cancel_cb)
        alert.show()

    def _alert_cancel_cb(self, alert, response_id):
        self.remove_alert(alert)
    
    # ------- Callbacks for Collaboration -------- #
    def buddy_joined(self, buddy):
        self._alert(_('Buddy joined'), _('%s joined' % buddy.props.nick))
        
    def buddy_left(self, buddy):
        self._alert(_('Buddy left'), _('%s left' % buddy.props.nick))
    
    def Play(self, x, y, sender=None):
        ''' Called when a stone was placed at x,y by sender'''
        # Discard a pass move received in our turn. Do it here for extra security
        if x == -1 and self.get_currentcolor() == self.get_playercolor():
            return
        self.insert_cb(None, x, y, False)
        
