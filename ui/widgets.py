"""Shared interaction rules: wheel scrolls, editing never starts on a double click."""
import math
from PySide6.QtCore import Qt,QObject,QEvent,QTimer,QPointF,Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication,QWidget,QAbstractSpinBox,QComboBox,QScrollArea,
    QPlainTextEdit,QTabBar,QTreeWidget,QAbstractItemView,QStyledItemDelegate,QDoubleSpinBox)

class WheelRouter(QObject):
    def __init__(self,root,fallback):
        super().__init__(root);self.root=root;self.fallback=fallback
        QApplication.instance().installEventFilter(self)
    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.Wheel or not isinstance(obj,QWidget):return False
        if not (obj is self.root or self.root.isAncestorOf(obj)):return False
        node=obj;protected=False;scroll=None
        while node is not None and node is not self.root:
            protected=protected or isinstance(node,(QAbstractSpinBox,QComboBox,QPlainTextEdit,QTabBar))
            if isinstance(node,QScrollArea):scroll=node;break
            node=node.parentWidget()
        if not protected:return False
        scroll=scroll or self.fallback()
        if scroll and scroll.isEnabled():
            viewport=scroll.viewport()
            forwarded=QWheelEvent(QPointF(viewport.rect().center()),event.globalPosition(),event.pixelDelta(),
                event.angleDelta(),event.buttons(),event.modifiers(),event.phase(),event.inverted())
            QApplication.sendEvent(viewport,forwarded)
        event.accept();return True
    def stop(self):QApplication.instance().removeEventFilter(self)

class ExpandingJson(QPlainTextEdit):
    """JSON shares the page scrollbar rather than adding an inner vertical scrollbar."""
    def __init__(self):
        super().__init__();self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self.fit_height)
    def fit_height(self):
        width=max(80,self.viewport().width()-18);metrics=self.fontMetrics()
        lines=sum(max(1,math.ceil(metrics.horizontalAdvance(line or ' ')/width)) for line in self.toPlainText().split('\n'))
        height=max(76,lines*metrics.lineSpacing()+28)
        if self.height()!=height:self.setFixedHeight(height)
    def resizeEvent(self,event):super().resizeEvent(event);self.fit_height()

class ColumnsDelegate(QStyledItemDelegate):
    def __init__(self,columns,numeric=(),parent=None):
        super().__init__(parent);self.columns=columns;self.numeric=numeric
    def createEditor(self,parent,option,index):
        if index.column() not in self.columns:return None
        if index.column() in self.numeric:
            editor=QDoubleSpinBox(parent);editor.setRange(-1000000,1000000);editor.setDecimals(3);return editor
        return super().createEditor(parent,option,index)
    def setEditorData(self,editor,index):
        if isinstance(editor,QDoubleSpinBox):editor.setValue(float(index.data()))
        else:super().setEditorData(editor,index)
    def setModelData(self,editor,model,index):
        if isinstance(editor,QDoubleSpinBox):model.setData(index,f'{editor.value():g}')
        else:super().setModelData(editor,model,index)

class AssetTree(QTreeWidget):
    def __init__(self):
        super().__init__();self.edit_timer=QTimer(self);self.edit_timer.setSingleShot(True)
        self.edit_timer.timeout.connect(self.delayed_edit);self.edit_target=None
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setItemDelegate(ColumnsDelegate({0,3},parent=self))
    def mousePressEvent(self,event):
        self.edit_timer.stop();item=self.itemAt(event.position().toPoint());column=self.columnAt(int(event.position().x()))
        selected=item is not None and item is self.currentItem() and item.isSelected()
        super().mousePressEvent(event)
        self.edit_target=(item,column) if selected and column in (0,3) and event.button()==Qt.MouseButton.LeftButton else None
    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if self.edit_target:self.edit_timer.start(QApplication.doubleClickInterval()+80)
    def mouseDoubleClickEvent(self,event):
        self.edit_timer.stop();self.edit_target=None;super().mouseDoubleClickEvent(event)
    def delayed_edit(self):
        if not self.edit_target:return
        item,column=self.edit_target;self.edit_target=None
        if self.currentItem() is item:self.editItem(item,column)
    def clear(self):
        self.edit_timer.stop();self.edit_target=None;super().clear()
