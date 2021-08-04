# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and 
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2022, Baycrest Centre for Geriatric Care ("Baycrest") and others
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this
# program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#   CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
#   Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
#   Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
#       The Virtual Brain: a simulator of primate brain network dynamics.
#   Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#

"""
Root class for export functionality.

.. moduleauthor:: Lia Domide <lia.domide@codemart.ro>
"""
import os
from datetime import datetime
from abc import ABCMeta, abstractmethod

from tvb.adapters.datatypes.db.mapped_value import DatatypeMeasureIndex
from tvb.adapters.exporters.exceptions import ExportException
from tvb.core.entities import load
from tvb.core.entities.load import load_entity_by_gid
from tvb.core.entities.model.model_datatype import DataTypeGroup
from tvb.core.entities.storage import dao
from tvb.core.neocom import h5
from tvb.core.neotraits._h5core import H5File
from tvb.core.services.project_service import ProjectService

# List of DataTypes to be excluded from export due to not having a valid export mechanism implemented yet.
from tvb.storage.storage_interface import StorageInterface

EXCLUDED_DATATYPES = ['Cortex', 'CortexActivity', 'CapEEGActivity', 'Cap', 'ValueWrapper', 'SpatioTermporalMask']


class ABCExporter(metaclass=ABCMeta):
    """
    Base class for all data type exporters
    This should provide common functionality for all TVB exporters.
    """

    @abstractmethod
    def get_supported_types(self):
        """
        This method specify what types are accepted by this exporter.
        Method should be implemented by each subclass and return
        an array with the supported types.

        :returns: an array with the supported data types.
        """
        pass

    def get_label(self):
        """
        This method returns a string to be used on the UI controls to initiate export

        :returns: string to be used on UI for starting this export.
                  By default class name is returned
        """
        return self.__class__.__name__

    def accepts(self, data):
        """
        This method specify if the current exporter can export provided data.
        :param data: data to be checked
        :returns: true if this data can be exported by current exporter, false otherwise.
        """
        effective_data_type = self._get_effective_data_type(data)

        # If no data present for export, makes no sense to show exporters
        if effective_data_type is None:
            return False

        # Now we should check if any data type is accepted by current exporter
        # Check if the data type is one of the global exclusions
        if hasattr(effective_data_type, "type") and effective_data_type.type in EXCLUDED_DATATYPES:
            return False

        for supported_type in self.get_supported_types():
            if isinstance(effective_data_type, supported_type):
                return True

        return False

    def _get_effective_data_type(self, data):
        """
        This method returns the data type for the provided data.
        - If current data is a simple data type is returned.
        - If it is an data type group, we return the first element. Only one element is
        necessary since all group elements are the same type.
        """
        # first check if current data is a DataTypeGroup
        if self.is_data_a_group(data):
            if self.skip_group_datatypes():
                return None

            data_types = ProjectService.get_datatypes_from_datatype_group(data.id)

            if data_types is not None and len(data_types) > 0:
                # Since all objects in a group are the same type it's enough
                return load_entity_by_gid(data_types[0].gid)
            else:
                return None
        else:
            return data

    def skip_group_datatypes(self):
        return False

    def _get_all_data_types_arr(self, data):
        """
        This method builds an array with all data types to be processed later.
        - If current data is a simple data type is added to an array.
        - If it is an data type group all its children are loaded and added to array.
        """
        # first check if current data is a DataTypeGroup
        if self.is_data_a_group(data):
            data_types = ProjectService.get_datatypes_from_datatype_group(data.id)

            result = []
            if data_types is not None and len(data_types) > 0:
                for data_type in data_types:
                    entity = load_entity_by_gid(data_type.gid)
                    result.append(entity)

            return result

        else:
            return [data]

    def is_data_a_group(self, data):
        """
        Checks if the provided data, ready for export is a DataTypeGroup or not
        """
        return isinstance(data, DataTypeGroup)

    def gather_datatypes_for_copy(self, data, dt_path_list):
        data_path = h5.path_for_stored_index(data)

        if data_path not in dt_path_list:
            dt_path_list.append(data_path)

        with H5File.from_file(data_path) as f:
            sub_dt_refs = f.gather_references()

            for _, ref_gid in sub_dt_refs:
                if ref_gid:
                    dt = load.load_entity_by_gid(ref_gid)
                    self.gather_datatypes_for_copy(dt, dt_path_list)

    def prepare_datatypes_for_export(self, data):
        all_datatypes = self._get_all_data_types_arr(data)

        # We are exporting a group of datatype measures so we need to find the group of time series
        if hasattr(all_datatypes[0], 'fk_source_gid'):
            ts = h5.load_entity_by_gid(all_datatypes[0].fk_source_gid)
            data_2 = dao.get_datatypegroup_by_op_group_id(ts.parent_operation.fk_operation_group)
            all_datatypes_2 = self._get_all_data_types_arr(data_2)
            all_datatypes = all_datatypes_2 + all_datatypes
        else:
            data_2 = dao.get_datatype_measure_group_from_ts_from_pse(all_datatypes[0].gid, DatatypeMeasureIndex)
            all_datatypes_2 = self._get_all_data_types_arr(data_2)
            all_datatypes = all_datatypes + all_datatypes_2

        if all_datatypes is None or len(all_datatypes) == 0:
            raise ExportException("Could not export a data type group with no data!")

        op_file_dict = dict()
        for dt in all_datatypes:
            h5_path = h5.path_for_stored_index(dt)
            StorageInterface().get_storage_manager(h5_path).remove_metadata('parent_burst', check_existence=True)
            op_folder = os.path.dirname(h5_path)
            op_file_dict[op_folder] = [h5_path]

            op = dao.get_operation_by_id(dt.fk_from_operation)
            vms = h5.gather_references_of_view_model(op.view_model_gid, os.path.dirname(h5_path), only_view_models=True)
            op_file_dict[op_folder].extend(vms[0])

            vm_path = h5.determine_filepath(op.view_model_gid, op_folder)
            StorageInterface().get_storage_manager(vm_path).remove_metadata('parent_burst', check_existence=True)

        return all_datatypes, op_file_dict

    @abstractmethod
    def export(self, data, project):
        """
        Actual export method, to be implemented in each sub-class.

        :param data: data type to be exported

        :param project: project that contains data to be exported

        :returns: a tuple with the following elements:

                        1. name of the file to be shown to user
                        2. full path of the export file (available for download)
                        3. boolean which specify if file can be deleted after download
        """
        pass

    @staticmethod
    def get_export_file_name(data, file_extension):
        data_type_name = data.__class__.__name__
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M")

        return "%s_%s%s" % (date_str, data_type_name, file_extension)

    def _get_export_file_name(self, data):
        """
        This method computes the name used to save exported data on user computer
        """
        file_ext = self.get_export_file_extension(data)
        return self.get_export_file_name(data, file_ext)

    @abstractmethod
    def get_export_file_extension(self, data):
        """
        This method computes the extension of the export file
        :param data: data type to be exported
        :returns: the extension of the file to be exported (e.g zip or h5)
        """
        pass
