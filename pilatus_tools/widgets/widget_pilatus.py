import pkg_resources
from PyQt5 import uic, QtCore
from matplotlib.widgets import RectangleSelector, Cursor
from PyQt5.Qt import QSplashScreen, QObject, QFont
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtGui import QPixmap, QCursor
from isstools.dialogs.BasicDialogs import message_box
from isstools.elements.widget_motors import UIWidgetMotors
from functools import partial
import json
from time import sleep
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar)
from matplotlib.figure import Figure
import matplotlib.patches as patches
import time as ttime
import numpy as np

import pyqtgraph as pg
pg.setConfigOption('leftButtonPan', False)

import sys
sys.path.append('/home/xf08id/Repos/')

from .figure_update import update_figure

ui_path = '/home/xf08id/Repos/xpilatus/pilatus_tools/ui/ui_pilatus.ui'


    # pkg_resources.resource_filename('pilatus_tools', 'ui/ui_pilatus.ui')
# spectrometer_image1 = pkg_resources.resource_filename('isstools', 'Resources/spec_image1.png')
# spectrometer_image2 = pkg_resources.resource_filename('isstools', 'Resources/spec_image2.png')

class UIPilatusMonitor(*uic.loadUiType(ui_path)):
    def __init__(self,
                detector_dict=None,
                # plan_processor=None,
                hhm=None,
                parent=None,
                 *args, **kwargs
                 ):
        super().__init__(*args, **kwargs)
        self.setupUi(self)
        self.parent = parent
        self.detector_dict = detector_dict
        # self.plan_processor = plan_processor
        self.hhm = hhm
        self.cur_mouse_coords = None

        self.polygon_roi_path = f'/nsls2/data/iss/legacy/xf08id/settings/json/pilatus_polygon_roi.json'
        with open(self.polygon_roi_path, 'r') as f:
            self.pilatus_polygon_roi = json.loads(f.read())

        self.pilatus100k_dict = self.detector_dict['Pilatus 100k']
        self.pilatus100k_device = self.detector_dict['Pilatus 100k']['device']
        # self.addCanvas()

        self.update_image_timer = QtCore.QTimer(self)
        self.update_image_timer.setInterval(1)
        # # # self.update_image_timer.timeout.connect(self.update_continuous_plot)
        self.update_image_timer.timeout.connect(self.plot_this)
        self.update_image_timer.start()

        self.update_counts_n_energy_timer = QtCore.QTimer(self)
        self.update_counts_n_energy_timer.setInterval(200)
        self.update_counts_n_energy_timer.timeout.connect(self.update_counts_n_energy)
        self.update_counts_n_energy_timer.start()

        self.subscription_dict = {'exposure': self.pilatus100k_device.cam.acquire_time,
                                  'num_of_images': self.pilatus100k_device.cam.num_images,
                                  'set_energy' : self.pilatus100k_device.cam.set_energy,
                                  'cutoff_energy': self.pilatus100k_device.cam.threshold_energy}


        self.gain_menu = {0: "7-30keV/Fast/LowG",
                          1: "5-18keV/Med/MedG",
                          2: "3-6keV/Slow/HighG",
                          3: "2-5keV/Slow/UltraG"}
        for i in range(4):
            self.comboBox_shapetime.addItem(self.gain_menu[i])

        # self.pilatus100k_device.cam.image_mode.set(0).wait()
        # self.pilatus100k_device.cam.trigger_mode.set(0).wait()

        self.pilatus100k_device.cam.image_mode.put(0)
        self.pilatus100k_device.cam.trigger_mode.put(0)



        self.comboBox_shapetime.currentIndexChanged.connect(self.change_pilatus_gain)
        self.pilatus100k_device.cam.gain_menu.subscribe(self.update_gain_combobox)

        self.radioButton_single_exposure.toggled.connect(self.update_acquisition_mode)
        self.radioButton_continuous_exposure.toggled.connect(self.update_acquisition_mode)
        # self.radioButton_detector_flying.toggled.connect(self.update_acquisition_mode)

        self.pushButton_start.clicked.connect(self.acquire_image)
        self.pushButton_stop.clicked.connect(self.stop_acquire_image)

        self.checkBox_detector_settings.clicked.connect(self.open_detector_setting)

        self.checkBox_enable_energy_change.clicked.connect(self.open_energy_change)
        # self.hhm.energy.user_readback.subscribe(self.read_mono_energy)
        self.pushButton_move_energy.clicked.connect(self.set_mono_energy)

        # self.pushButton_clear_box.clicked.connect(self.clear_selection_box)

        self._min = 0
        self._max = 5

        self.label_min.setText(f'{self._min}')
        self.label_max.setText(f'{self._max}')

        self.label_x.setText(u"\u25b4" + " " + u"\u25be")
        self.label_y.setText(u"\u25c2" + "  " + u"\u25b8")
        self.label_x.setFont(QFont('Arial', 16))
        self.label_y.setFont(QFont('Arial', 16))
        # self.label_x.

        self._patches = {}

        self.lineEdit_min.returnPressed.connect(self.update_min_range)
        self.lineEdit_max.returnPressed.connect(self.update_max_range)
        self.horizontalSlider_min.sliderReleased.connect(self.update_slider_min_range)
        self.horizontalSlider_max.sliderReleased.connect(self.update_slider_max_range)


        # self.RS = RectangleSelector(self.figure_pilatus_image.ax,
        #                                             self.line_select_callback,
        #                                             drawtype='box',
        #                                             useblit=True,
        #                                             button=[1, 3],
        #                                             minspanx=5,
        #                                             minspany=5,
        #                                             spancoords='pixels',
        #                                             interactive=True)

        # for i in range(1,5):
        #     self.add_roi_counts_total(i)

        for i in range(1, 5):
            self.add_roi_parameters(i)

        for _keys in self.subscription_dict.keys():
            self.add_pilatus_attribute(_keys)

        # for i in range(1, 5):
        #     getattr(self, 'checkBox_roi' + str(i)).toggled.connect(self.add_roi_box)

        self.checkBox_auto_scale.toggled.connect(self.auto_scale_image)

        # for i in range(1,5):
        #     getattr(self, 'pushButton_edit_roi' + str(i)).clicked.connect(self.set_roi)

        self.last_image_update_time = 0
        self.colors = {1: 'r',
                  2: 'c',
                  3: 'g',
                  4: 'y'
                  }

        self.checkBox_roi1.setStyleSheet("QCheckBox::checked"
                                         "{"
                                         "background-color : red"
                                         "}")

        self.checkBox_roi2.setStyleSheet("QCheckBox::checked"
                                         "{"
                                         "background-color : cyan"
                                         "}")

        self.checkBox_roi3.setStyleSheet("QCheckBox::checked"
                                         "{"
                                         "background-color : lime"
                                         "}")

        self.checkBox_roi4.setStyleSheet("QCheckBox::checked"
                                         "{"
                                         "background-color : yellow"
                                         "}")

        self.create_plot_widget()


        for i in range(1, 5):
            getattr(self, 'checkBox_roi' + str(i)).toggled.connect(self.add_roi_box)
            indx = str(i)
            self.roi_boxes[indx].sigRegionChangeFinished.connect(partial(self.read_new_pos_n_size, indx))

        self.checkBox_show_polygon_rois.toggled.connect(self.add_polygon_rois)

    def create_plot_widget(self):
        self.window = pg.GraphicsLayoutWidget()
        # self.window.setBackground('white')
        self.verticalLayout_pilatus_image.addWidget(self.window)
        self.plot = self.window.addPlot()
        # self.plot.hideAxis('bottom')
        # self.plot.hideAxis('left')

        self.set_n_add_image_properties()

    def set_n_add_image_properties(self):
        self.image = pg.ImageItem(aspectLocked=True)
        self.color_map = pg.colormap.getFromMatplotlib(name='jet')
        self.image.setColorMap(self.color_map)
        self.plot.addItem(self.image)
        self.set_n_add_roi_properties()


    def set_n_add_roi_properties(self):
        self.colors = {'1': 'red',
                       '2': 'cyan',
                       '3': 'lime',
                       '4': 'yellow'}

        self.roi_boxes = {}

        for i in range(1, 5):
            indx = str(i)
            x, y, dx, dy = self.pilatus100k_device.get_roi_coords(i)
            self.roi_boxes[indx] = pg.ROI([y, x], [dy, dx], pen=pg.mkPen(self.colors[indx], width=5),
                                          rotatable=False, aspectLocked=False)

            self.roi_boxes[indx].addScaleHandle([0.5, 0], [0.5, 1])
            self.roi_boxes[indx].addScaleHandle([0, 0.5], [1, 0.5])


        self.colors_polygon = {'main': '#1f77b4',  # 'tab:blue',
                               'aux2': '#ff7f0e',  # 'tab:orange',
                               'aux3': '#2ca02c',  # 'tab:green',
                               'aux4': '#d62728',  # 'tab:red',
                               'aux5': '#9467bd', }  # 'tab:purple'
        self.gui_polygon_roi = {}


        for crystal, poly in self.pilatus_polygon_roi.items():
            poly_T = [[j, i] for i, j in poly]
            polygon_obj = pg.PolyLineROI(poly_T, closed=True,
                                         pen=pg.mkPen(self.colors_polygon[crystal], width=5))
            polygon_obj.sigRegionChangeFinished.connect(self.save_polygon_roi_coords)
            self.gui_polygon_roi[crystal] = polygon_obj

        self.get_polygon_roi_labels()

    def get_polygon_roi_labels(self):
        self.gui_polygon_label = {}
        for crystal, polygon_obj in self.gui_polygon_roi.items():
            font = QFont()
            font.setBold(True)
            font.setPointSize(16)
            label = pg.TextItem(crystal, color=self.colors_polygon[crystal], fill='w', anchor=(0.5, 0.5))
            label.setFont(font)
            self.gui_polygon_label[crystal] = label
        self.set_polygon_roi_label_positions()

    def set_polygon_roi_label_positions(self, dy=25):
        for crystal, polygon_obj in self.gui_polygon_roi.items():
            _x, _y, _dx, _dy = polygon_obj.boundingRect().getRect()
            self.gui_polygon_label[crystal].setPos(_x + _dx/2, _y + _dy + dy)

    def plot_this(self):

        _img = self.pilatus100k_device.image.array_data.get()
        _img = _img.reshape(195,487) #[:, ::-1]

        # _img = self.pilatus100k_device.image.array_data.value.reshape(195, 487)
        ## Dead pixels
        # _img[158, 11] = 0
        # _img[15, 352] = 0
        # _img[171, 364] = 0
        # _img[171, 365] = 0

        self.image.setImage(_img)
        self.image.setLevels([self._min, self._max])


    def add_roi_box(self):
        sender_object = QObject().sender()
        indx = sender_object.text()

        if not sender_object.isChecked():
            self.plot.removeItem(self.roi_boxes[indx])
        else:
            self.plot.addItem(self.roi_boxes[indx])

    def read_new_pos_n_size(self, roi_indx):
        new_pos = self.roi_boxes[roi_indx].pos()
        new_size = self.roi_boxes[roi_indx].size()

        print(f"{new_pos = } {new_size = }")

        getattr(self.pilatus100k_device, 'roi' + roi_indx).min_xyz.min_x.put(new_pos[1])
        getattr(self.pilatus100k_device, 'roi' + roi_indx).min_xyz.min_y.put(new_pos[0])

        getattr(self.pilatus100k_device, 'roi' + roi_indx).size.x.put(new_size[1])
        getattr(self.pilatus100k_device, 'roi' + roi_indx).size.y.put(new_size[0])

        # self.pilatus100k_device.cam.acquire.subscribe(self.update_image_widget)

    def add_polygon_rois(self, checked_state):
        print(checked_state)
        for crystal, obj in self.gui_polygon_roi.items():
            if checked_state:
                self.plot.addItem(obj)
            else:
                self.plot.removeItem(obj)

        for crystal, obj in self.gui_polygon_label.items():
            if checked_state:
                self.plot.addItem(obj)
            else:
                self.plot.removeItem(obj)


    @property
    def gui_polygon_roi_coords(self):
        output = {}
        for crystal, obj in self.gui_polygon_roi.items():
            points = []
            for handle in obj.getHandles():
                y, x = handle.pos()
                points.append([np.round(x, 1), np.round(y, 1)])
            output[crystal] = points
        return output


    def save_polygon_roi_coords(self):
        print('POLYGON ROI COORDINATES HAVE BEEN UPDATED. NOW STORING THEM ON DISC.')
        self.set_polygon_roi_label_positions()
        with open(self.polygon_roi_path, 'w') as f:
            json.dump(self.gui_polygon_roi_coords, f)

    def update_counts_n_energy(self):
        try:

            _energy = self.hhm.energy.user_readback.get()
            _det_state = self.pilatus100k_device.cam.detector_state.get()
            if _det_state == 1:
                self.label_detector_state.setText('Acquiring')
                self.label_detector_state.setStyleSheet('background-color: rgb(95,249,95)')
            else:
                self.label_detector_state.setText('Idle')
                self.label_detector_state.setStyleSheet('background-color: rgb(255,0,0)')


            self.label_current_energy.setText(f'{_energy:4.1f} eV')
            for ch in range(1,5):
                _cnts = getattr(self.pilatus100k_device, 'stats' + str(ch)).total.get()
                getattr(self, 'label_counts_roi' + str(ch)).setText(f'{_cnts} cts')
        except Exception as e:
            print("Could not update the counts and energy Error:", e)


#### Update minimum and maximum range for the 2D plot


    def update_slider_min_range(self):
        _min = self.horizontalSlider_min.value()

        QToolTip.showText(QCursor.pos(), f'{_min}')

        if _min < self._max:
            self.label_message.setText(" ")
            self._min = _min
            # self.update_pilatus_image()
        else:
            self.label_message.setText("Error Min should be smaller then Max")


    def update_slider_max_range(self):
        _max = self.horizontalSlider_max.value()
        QToolTip.showText(QCursor.pos(), f'{_max}')

        if _max > self._min:
            self.label_message.setText(" ")
            self._max = _max
            # self.update_pilatus_image()
        else:
            self.label_message.setText("Error Max should be larger then Min")

    def auto_scale_image(self):
        if self.checkBox_auto_scale.isChecked():
            self._min = None
            self._max = None
            # self.update_pilatus_image()

    def update_min_range(self):
        _value = int(self.lineEdit_min.text().split()[0])
        self._min = _value

        if self._max is None:
            self.label_message.setText(" ")
            self._max = self._min + 1
            self.label_max.setText(f"{self._max}")

        if self._min < self._max:
            self.label_message.setText(" ")
            self.label_min.setText(f"{self._min}")
            self.horizontalSlider_min.setValue(self._min)
            # self.update_pilatus_image()
        else:
            self.label_message.setText("Error Min should be smaller then Max")

    def update_max_range(self):
        _value = int(self.lineEdit_max.text().split()[0])
        self._max = _value

        if self._min is None:
            self.label_message.setText(" ")
            self._min = self._max - 1
            self.label_min.setText(f"{self._min}")

        if self._max > self._min:
            self.label_message.setText(" ")
            self.label_max.setText(f"{self._max}")
            self.horizontalSlider_max.setValue(self._max)
            # self.update_pilatus_image()
        else:
            self.label_message.setText("Error Max should be larger then Min")

#### Update minimum and maximum range for the 2D plot

#### Update Roi value

    # def set_roi(self):
    #     sender = QObject()
    #     sender_object = sender.sender()
    #     object_name = sender_object.objectName()
    #     _roi = object_name[-4:]
    #     _roi_number = int(object_name[-1])
    #     if sender_object.isChecked():
    #         if getattr(self, 'checkBox_' + _roi).isChecked():
    #             x, y, dx, dy = self.pilatus100k_device.get_roi_coords(_roi_number)
    #             self.RS.set_active(True)
    #             self.RS.set_visible(True)
    #             self.RS.extents = y, dy+y, x, x+dx
    #             self.canvas_pilatus_image.draw_idle()
    #     else:
    #         self.RS.set_active(False)
    #         self.RS.set_visible(False)
    #         self.canvas_pilatus_image.draw_idle()
    #         coord = self.RS.corners
    #         x = coord[1][0]
    #         w = coord[1][2] - coord[1][0]
    #         y = coord[0][0]
    #         h = coord[0][2] - coord[0][0]
    #         getattr(self, f'spinBox_roi{_roi_number}_min_x').setValue(int(x))
    #         getattr(self, f'spinBox_roi{_roi_number}_min_y').setValue(int(y))
    #         getattr(self, f'spinBox_roi{_roi_number}_width').setValue(int(w))
    #         getattr(self, f'spinBox_roi{_roi_number}_height').setValue(int(h))
    #         self.update_roi_box()
    #
    #
    # # def add_roi_counts_total(self, ch):
    # #     def update_roi_counts(value, **kwargs):
    # #         getattr(self, 'label_counts_roi'+str(ch)).setText(f'{value} cts')
    # #
    # #     getattr(self.pilatus100k_device, 'stats'+str(ch)).total.subscribe(update_roi_counts)
    #f
    def add_roi_parameters(self, ch):
        def update_roix_parameters(value, **kwargs):
            getattr(self, 'spinBox_roi' + str(ch) + '_min_x').setValue(value)
            _pos_y = getattr(self.pilatus100k_device, 'roi' + str(ch)).min_xyz.min_y.get()
            self.roi_boxes[str(ch)].setPos([_pos_y, value])

        def update_roiy_parameters(value, **kwargs):
            getattr(self, 'spinBox_roi' + str(ch) + '_min_y').setValue(value)
            _pos_x = getattr(self.pilatus100k_device, 'roi' + str(ch)).min_xyz.min_x.get()
            self.roi_boxes[str(ch)].setPos([value, _pos_x])

        def update_roix_size_parameters(value, **kwargs):
            getattr(self, 'spinBox_roi' + str(ch) + '_width').setValue(value)
            _size_y = getattr(self.pilatus100k_device, 'roi' + str(ch)).size.y.get()
            self.roi_boxes[str(ch)].setSize([_size_y, value])

        def update_roiy_size_parameters(value, **kwargs):
            getattr(self, 'spinBox_roi' + str(ch) + '_height').setValue(value)
            _size_x = getattr(self.pilatus100k_device, 'roi' + str(ch)).size.x.get()
            self.roi_boxes[str(ch)].setSize([value, _size_x])

        getattr(self.pilatus100k_device, 'roi' + str(ch)).min_xyz.min_x.subscribe(update_roix_parameters)
        getattr(self.pilatus100k_device, 'roi' + str(ch)).min_xyz.min_y.subscribe(update_roiy_parameters)

        getattr(self.pilatus100k_device, 'roi' + str(ch)).size.x.subscribe(update_roix_size_parameters)
        getattr(self.pilatus100k_device, 'roi' + str(ch)).size.y.subscribe(update_roiy_size_parameters)

        getattr(self, "spinBox_roi" + str(ch) + "_min_x").editingFinished.connect(partial(self.update_roix_value, str(ch)))

        getattr(self, 'spinBox_roi' + str(ch) + '_min_y').editingFinished.connect(partial(self.update_roiy_value, str(ch)))

        getattr(self, 'spinBox_roi' + str(ch) + '_width').editingFinished.connect(partial(self.update_roix_size_value, str(ch)))

        getattr(self, 'spinBox_roi' + str(ch) + '_height').editingFinished.connect(partial(self.update_roiy_size_value, str(ch)))
    #
    #
    #
    def update_roix_value(self, ch):
        sender = QObject()
        sender_object = sender.sender()
        sender_obj_value = sender_object.value()
        getattr(self.pilatus100k_device, 'roi' + ch).min_xyz.min_x.put(sender_obj_value)


    def update_roiy_value(self, ch):
        sender = QObject()
        sender_object = sender.sender()
        sender_obj_value = sender_object.value()
        getattr(self.pilatus100k_device, 'roi' + ch).min_xyz.min_y.put(sender_obj_value)


    def update_roix_size_value(self, ch):
        sender = QObject()
        sender_object = sender.sender()
        sender_obj_value = sender_object.value()
        getattr(self.pilatus100k_device, 'roi' + ch).size.x.put(sender_obj_value)

    def update_roiy_size_value(self, ch):
        sender = QObject()
        sender_object = sender.sender()
        sender_obj_value = sender_object.value()
        getattr(self.pilatus100k_device, 'roi' + ch).size.y.put(sender_obj_value)
    #
    #
    #
    # def update_roi_box(self):
    #     for i in range(1,5):
    #         if getattr(self, 'checkBox_roi' + str(i)).isChecked():
    #             obj_name = getattr(self, 'checkBox_roi' + str(i)).objectName()
    #             self._patches[obj_name].remove()
    #             self.canvas_pilatus_image.draw_idle()
    #
    #             x, y, dx, dy = self.pilatus100k_device.get_roi_coords(i)
    #             rect = patches.Rectangle((y, x), dy, dx, linewidth=1, edgecolor=self.colors[i], facecolor='none')
    #             self._patches[obj_name] = self.figure_pilatus_image.ax.add_patch(rect)
    #             self.canvas_pilatus_image.draw_idle()
    #
    # def add_roi_box(self):
    #     sender = QObject()
    #     sender_object = sender.sender()
    #     sender_obj_name = sender_object.objectName()
    #     sender_obj_value = sender_object.text()
    #     if sender_object.isChecked():
    #         x, y, dx, dy = self.pilatus100k_device.get_roi_coords(int(sender_obj_value))
    #         rect = patches.Rectangle((y, x), dy, dx, linewidth=1, edgecolor=self.colors[int(sender_obj_value)],
    #                                  facecolor='none')
    #         self._patches[sender_obj_name] = self.figure_pilatus_image.ax.add_patch(rect)
    #         self.canvas_pilatus_image.draw_idle()
    #     if not sender_object.isChecked():
    #         try:
    #             self._patches[sender_obj_name].remove()
    #             self.canvas_pilatus_image.draw_idle()
    #         except:
    #             pass

#### Update Roi value



##### Update, Add Pilatus Image
    # def update_pilatus_image(self):
    #
    #     try:
    #
    #         self.last_image_update_time = ttime.time()
    #         self.figure_pilatus_image.ax.clear()
    #         self.toolbar_pilatus_image.update()
    #
    #
    #         # update_figure([self.figure_pilatus_image.ax],
    #         #               self.toolbar_pilatus_image,
    #         #               self.canvas_pilatus_image)
    #
    #         _img = self.pilatus100k_device.image.array_data.get()
    #         _img = _img.reshape(195, 487)
    #
    #         # _img = self.pilatus100k_device.image.array_data.value.reshape(195, 487)
    #         ## Dead pixels
    #         _img[158, 11] = 0
    #         _img[15, 352] = 0
    #         _img[171, 364] = 0
    #         _img[171, 365] = 0
    #
    #         # self._min = _img.min()
    #         # self._max = _img.max()
    #         self.horizontalSlider_min.setMinimum(_img.min())
    #         self.horizontalSlider_max.setMinimum(_img.min())
    #         self.horizontalSlider_min.setMaximum(_img.max())
    #         self.horizontalSlider_max.setMaximum(_img.max())
    #         # self.horizontalSlider_min.setValue(_img.min())
    #         # self.horizontalSlider_max.setValue(_img.max())
    #
    #         # self.label_min.setText (str(self._min))
    #         # self.label_max.setText(str(self._max))
    #
    #
    #
    #
    #         self.figure_pilatus_image.ax.imshow(_img.T, interpolation='nearest', aspect='auto', vmin=self._min, vmax=self._max)
    #
    #
    #         # Add the patch to the Axes
    #
    #         for i in range(1,5):
    #             if getattr(self, 'checkBox_roi' + str(i)).isChecked():
    #                 x, y, dx, dy = self.pilatus100k_device.get_roi_coords(i)
    #                 rect = patches.Rectangle((y, x), dy, dx, linewidth=1, edgecolor=self.colors[i], facecolor='none')
    #                 self._patches['checkBox_roi' + str(i)] = self.figure_pilatus_image.ax.add_patch(rect)
    #                 # self.canvas_pilatus_image.draw_idle()
    #             if not getattr(self, 'checkBox_roi' + str(i)).isChecked():
    #                 try:
    #                     self._patches['checkBox_roi' + str(i)].remove()
    #                     # self.canvas_pilatus_image.draw_idle()
    #                 except:
    #                     pass
    #
    #
    #
    #         # # self.figure_pilatus_image.ax.autoscale(True)
    #         self.figure_pilatus_image.ax.set_xticks([])
    #         self.figure_pilatus_image.ax.set_yticks([])
    #         self.figure_pilatus_image.tight_layout(pad=0)
    #         self.canvas_pilatus_image.draw_idle()
    #
    #     except Exception as e:
    #         print('Could not update the image. Error: ',e)

    # def update_continuous_plot(self):
    #     if self.radioButton_continuous_exposure.isChecked() or self.checkBox_detector_flying.isChecked():
    #         try:
    #             self.update_pilatus_image()
    #         except:
    #             pass

    # def update_image_widget(self, value, old_value, **kwargs):
    #     if value == 0 and old_value == 1:
    #         self.update_pilatus_image()
        #     print('acquiring')
        # print('done')
        # self.update_pilatus_image()

        # _img_mode = self.pilatus100k_device.cam.image_mode.get()
        # _trig_mode = self.pilatus100k_device.cam.trigger_mode.get()
        #
        # # i =0
        # if (_img_mode == 2 and _trig_mode == 4) or (_img_mode == 0 and _trig_mode == 0):
        #     self.update_pilatus_image()
        # else:
        #     if (value == 0) and (old_value == 1):
        #         if (ttime.time() - self.last_image_update_time) > 0.1:
        #             self.update_pilatus_image()
        #     # if (ttime.time() - self.last_image_update_time) > 0.1:
        #     #     self.update_pilatus_image()

    # def addCanvas(self):
    #     self.figure_pilatus_image = Figure()
    #     self.figure_pilatus_image.set_facecolor(color='#FcF9F6')
    #     self.canvas_pilatus_image = FigureCanvas(self.figure_pilatus_image)
    #     self.toolbar_pilatus_image = NavigationToolbar(self.canvas_pilatus_image, self, coordinates=True)
    #     self.verticalLayout_pilatus_image.addWidget(self.toolbar_pilatus_image)
    #     self.verticalLayout_pilatus_image.addWidget(self.canvas_pilatus_image, stretch=1)
    #     self.figure_pilatus_image.ax = self.figure_pilatus_image.add_subplot(111)
    #
    #     self.canvas_pilatus_image.draw_idle()
    #     self.figure_pilatus_image.tight_layout()
    #
    #     # self.figure_pilatus_image.ax.set_yticks = ([])
    #     # self.figure_pilatus_image.ax.set_xticks = ([])
    #     #
    #     # self.canvas_pilatus_image.draw_idle()
    #
    #
    #     # cursor = Cursor(self.figure_pilatus_image.ax, useblit=True, color='green', linewidth=0.75)
    #     #
    #     # self.cid_start = self.canvas_pilatus_image.mpl_connect('button_press_event', self.roi_mouse_click_start)
    #     # self.cid_move = self.canvas_pilatus_image.mpl_connect('motion_notify_event', self.roi_mouse_click_move)
    #     # self.cid_finish = self.canvas_pilatus_image.mpl_connect('button_release_event', self.roi_mouse_click_finish)
    #
    # def line_select_callback(self, eclick, erelease):
    #     pass
    #     #
    #     # x1, y1 = eclick.xdata, eclick.ydata
    #     # x2, y2 = erelease.xdata, erelease.ydata
    #     # print(f'{x1 = :3.3f} {y1 = :3.3f} {x2 = :3.3f} {y2 = :3.3f}')
    #     #
    #     # for i in range(1,5):
    #     #     if getattr(self, 'checkBox_roi' + str(i)).isChecked():
    #     #         getattr(self, "spinBox_roi" + str(i) + "_min_x").setValue(int(y1))
    #     #         getattr(self, 'spinBox_roi' + str(i) + '_min_y').setValue(int(x1))
    #     #         getattr(self, 'spinBox_roi' + str(i) + '_width').setValue(int(y2-y1))
    #     #         getattr(self, 'spinBox_roi' + str(i) + '_height').setValue(int(x2-x1))
    #     #     self.update_roi_box()
    #
    # def roi_mouse_click_start(self, event):
    #     if event.button == 3:
    #         self.cur_mouse_coords = (event.xdata, event.ydata)
    #         print('MOTION STARTED')
    #
    # def roi_mouse_click_move(self, event):
    #     if self.cur_mouse_coords is not None:
    #         self.cur_mouse_coords = (event.xdata, event.ydata)
    #         print(self.cur_mouse_coords)
    #
    # def roi_mouse_click_finish(self, event):
    #     if event.button == 3:
    #         if self.cur_mouse_coords is not None:
    #             self.cur_mouse_coords = None
    #             print('MOTION FINISHED')

##### Update, Add Pilatus Image

##### Set, read and change mono energy

    def set_mono_energy(self):
        if self.checkBox_enable_energy_change.isChecked():
            _energy = self.spinBox_mono_energy.value()
            self.hhm.energy.user_setpoint.set(_energy).wait()

    # def read_mono_energy(self, value, **kwargs):
    #     self.label_current_energy.setText(f'{value:4.1f} eV')

    def open_energy_change(self):
        if self.checkBox_enable_energy_change.isChecked():
            self.spinBox_mono_energy.setEnabled(True)
        else:
            self.spinBox_mono_energy.setEnabled(False)


    def open_detector_setting(self):

        if self.checkBox_detector_settings.isChecked():
            self.lineEdit_set_energy.setEnabled(True)
            self.lineEdit_cutoff_energy.setEnabled(True)
        else:
            self.lineEdit_set_energy.setEnabled(False)
            self.lineEdit_cutoff_energy.setEnabled(False)

    def stop_acquire_image(self):
        self.pilatus100k_device.cam.acquire.put(0)
        # self.update_pilatus_image()

    def acquire_image(self):

        # self.plan_processor.add_plan_and_run_if_idle('take_pil100k_test_image_plan', {})
        self.pilatus100k_device.cam.acquire.put(1)
        # self.update_pilatus_image()




    def update_acquisition_mode(self):
        if self.radioButton_single_exposure.isChecked():

            self.pilatus100k_device.cam.image_mode.set(0).wait()
            self.pilatus100k_device.cam.trigger_mode.set(0).wait()
        elif self.radioButton_continuous_exposure.isChecked():
            self.pilatus100k_device.cam.image_mode.set(2).wait()
            self.pilatus100k_device.cam.trigger_mode.set(4).wait()
        else:
            self.pilatus100k_device.cam.image_mode.set(1).wait()
            self.pilatus100k_device.cam.trigger_mode.set(3).wait()



    def add_pilatus_attribute(self, attribute_key):

        def update_item(_attr_key, _attr_signal):
            _current_value = getattr(self, "lineEdit_"+_attr_key).text()
            _current_value = float(_current_value)
            _attr_signal.set(_current_value).wait()

        def update_item_value(value ,**kwargs):
            if attribute_key == "exposure":
                unit = 's'
            elif attribute_key == 'num_of_images':
                unit = " "
            else:
                unit = "keV"
            getattr(self, "label_" + attribute_key).setText(f"{value:2.3f} {unit}")
            getattr(self, "lineEdit_" + attribute_key).setText(f"{value:2.3f}")

        # getattr(self, "lineEdit_" + attribute_key).setKeyboardTracking(False)
        getattr(self, "lineEdit_" + attribute_key).returnPressed.connect(partial(update_item, attribute_key, self.subscription_dict[attribute_key]))
        self.subscription_dict[attribute_key].subscribe(update_item_value)

    def change_pilatus_gain(self):
        _current_indx = self.comboBox_shapetime.currentIndex()
        self.pilatus100k_device.cam.gain_menu.set(_current_indx).wait()

    def update_gain_combobox(self, value, **kwargs):
        self.label_gain.setText(f"{self.gain_menu[value]}")
