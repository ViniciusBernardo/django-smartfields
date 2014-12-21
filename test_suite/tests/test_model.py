import os, time
from django.core.files.base import File
from django.db.models.fields.files import FileDescriptor
from django.db.utils import ProgrammingError
from django.test import TestCase
from django.utils import six

from smartfields.models import SmartfieldsModelMixin

from sample_app.models import ProcessorTestingModel, FilesTestingModel, ImageTestingModel, \
    DependencyTestingModel
from sample_app.utils import add_base, remove_folder_content


class ProcessingTestCase(TestCase):

    def test_model_setup(self):
        instance = ProcessorTestingModel()
        self.assertIsInstance(instance, SmartfieldsModelMixin)
        self.assertIsNotNone(getattr(instance, '_smartfields_managers', None))

    def test_individual_field_processing(self):
        instance = ProcessorTestingModel(field_1=six.text_type('foo bar'))
        instance.smartfields_process(field_names=['field_3'])
        self.assertEqual(instance.field_2, "")
        self.assertEqual(instance.field_3, "foo-bar")
        self.assertEqual(instance.field_4, "foo-bar")
        # also tests SlugProcessor
        instance.smartfields_process(field_names=['field_1'])
        self.assertEqual(instance.field_1, "Foo_Bar")
        self.assertEqual(instance.field_2, "foo-bar")
        self.assertEqual(instance.field_3, "foo-bar")

    def test_processing_order(self):
        instance = ProcessorTestingModel(field_1=six.text_type('foo bar'))
        instance.smartfields_process(field_names=['field_1', 'field_3'])
        self.assertEqual(instance.field_1, "Foo_Bar")
        self.assertEqual(instance.field_2, "foo-bar")
        self.assertEqual(instance.field_3, "foo_bar")
        instance = ProcessorTestingModel(field_1=six.text_type('foo bar'))
        instance.smartfields_process(field_names=['field_3', 'field_1'])
        self.assertEqual(instance.field_1, "Foo_Bar")
        self.assertEqual(instance.field_2, "foo-bar")
        self.assertEqual(instance.field_3, "foo-bar") # different then above: _

    def test_file_field(self):
        instance = FilesTestingModel.objects.create()
        # test default static
        self.assertEqual(instance.field_1.url, "/static/defaults/foo.txt")
        self.assertEqual(instance.field_2_foo.url, "/static/defaults/foo.txt")
        self.assertEqual(instance.bar.url, "/static/defaults/bar.txt")
        # test assignment of file
        file = open(add_base("media/foo.txt"), 'w')
        file.write("foo bar")
        file.close()
        instance.field_1 = "foo.txt"
        instance.save()
        self.assertEqual(instance.field_1.url, "/media/foo.txt")
        # test deletion of file together with instance
        instance.delete()
        self.assertRaises(IOError, open, add_base("media/foo.txt"))

    def test_image_field_mimic_django(self):
        instance = ImageTestingModel.objects.create()
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        instance.image_1 = lenna_rect
        instance.image_2 = lenna_rect
        instance.save()
        # make sure width and heigth values are correct and same as django's
        self.assertEqual(instance.image_1_width, instance.image_2_width)
        self.assertEqual(instance.image_1_height, instance.image_2_height)
        self.assertEqual(instance.image_2_width, 400)
        self.assertEqual(instance.image_2_height, 225)
        lenna_rect.close()
        # make sure values are saved properly
        instance = ImageTestingModel.objects.get(pk=instance.pk)
        self.assertEqual(instance.image_2_width, 400)
        self.assertEqual(instance.image_2_height, 225)
        # make sure image is still there and can properly retrieve dims
        self.assertEqual(instance.image_2.width, 400)
        self.assertEqual(instance.image_2.height, 225)
        self.assertEqual(instance.image_1.url, "/media/image_1/lenna_rect.jpg")
        self.assertEqual(instance.image_2.url, "/media/image_2/lenna_rect.jpg")
        
        # test image replacing
        lenna_square = File(open(add_base("static/images/lenna_square.png"), 'rb'))
        instance.image_2 = lenna_square
        instance.save()
        self.assertRaises(IOError, open, add_base("media/image_2/lenna_rect.jpg"))
        self.assertEqual(instance.image_2.width, 512)
        self.assertEqual(instance.image_2.height, 512)
        instance.image_2 = None
        instance.save()
        self.assertIsNone(instance.image_2_width)
        self.assertIsNone(instance.image_2_height)
        # remove django's ImageFieldFile manually
        instance.image_1.delete()
        instance.delete()
        self.assertRaises(IOError, open, add_base("media/image_2/lenna_square.png"))

    def test_image_processor(self):
        instance = ImageTestingModel.objects.create()
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        instance.image_3 = lenna_rect
        instance.save()
        # make sure conversion went through properly
        self.assertEquals(instance.image_3_png.width, 200)
        self.assertEquals(instance.image_3_png.height, 112)
        # save instance, so files get commited to storage
        path = instance.image_3.path
        path_png = instance.image_3_png.path
        # check to see that files got commited
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(path_png))
        # make sure dependency gets reattached as expected
        instance = ImageTestingModel.objects.get(pk=instance.pk)
        self.assertEquals(instance.image_3_png.width, 200)
        self.assertEquals(instance.image_3_png.height, 112)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(path_png))
        # test problematic processor (JPEG2000 is missing a required library)
        instance.image_4 = lenna_rect
        instance.save()
        self.assertEqual(instance.smartfields_get_field_status('image_4'), {
            'state': 'error', 
            'messages': [
                'ProcessingError: There was a problem with image conversion: encoder '
                'jpeg2k not available'
            ], 
            'app_label': 'sample_app', 
            'pk': 1, 
            'field_name': 'image_4', 
            'model_name': 'imagetestingmodel'
        })
        lenna_rect.close()
        # delete instance and check if everything is cleaned up
        instance.delete()
        self.assertRaises(IOError, open, path)
        self.assertRaises(IOError, open, path_png)

    def test_self_dependency(self):
        instance = DependencyTestingModel.objects.create()
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        instance.image_1 = lenna_rect
        instance.save()
        self.assertEqual(instance.image_1.width, 50)
        self.assertEqual(
            instance.image_1.url,
            "/media/sample_app/dependencytestingmodel/%s/image_1.bmp" % instance.pk)
        self.assertEqual(instance.image_1_gif.width, 50)
        self.assertEqual(
            instance.image_1_gif.url,
            "/media/sample_app/dependencytestingmodel/%s/image_1_gif.gif" % instance.pk)
        instance.delete()
        lenna_rect.close()

    def test_value_restoration_1(self):
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        text_file = File(open(add_base("static/defaults/foo.txt"), 'rb'))
        instance = DependencyTestingModel.objects.create()
        instance.image_1 = lenna_rect
        instance.save()
        lenna_rect.close()
        image_1 = instance.image_1
        image_1_gif = instance.image_1_gif
        instance.image_1 = text_file
        instance.save()
        self.assertIs(instance.image_1, image_1)
        self.assertIs(instance.image_1_gif, image_1_gif)
        instance.delete()
        text_file.close()

    def test_value_restoration_2(self):
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        text_file = File(open(add_base("static/defaults/foo.txt"), 'rb'))
        instance = DependencyTestingModel.objects.create()
        instance.image_2 = lenna_rect
        instance.save()
        lenna_rect.close()
        image_3 = instance.image_3
        image_4 = instance.image_4
        image_3_path = instance.image_3.path
        image_4_path = instance.image_4.path
        instance.image_2 = text_file
        instance.save()
        self.assertEqual(instance.image_3, image_3)
        self.assertEqual(instance.image_4, image_4)
        self.assertEqual(instance.image_3.path, image_3.path)
        self.assertEqual(instance.image_4.path, image_4.path)
        instance.delete()
        text_file.close()

    def test_forward_dependency(self):
        instance = DependencyTestingModel.objects.create()
        lenna_rect = File(open(add_base("static/images/lenna_rect.jpg"), 'rb'))
        instance.image_3 = lenna_rect
        instance.image_4 = lenna_rect
        instance.save()
        image_3_path = instance.image_3.path
        image_4_path = instance.image_4.path
        self.assertEqual(instance.image_3.width, 400)
        self.assertEqual(instance.image_4.width, 400)
        self.assertEqual(
            instance.image_3.url,
            "/media/sample_app/dependencytestingmodel/%s/image_3.jpg" % instance.pk)
        self.assertEqual(
            instance.image_4.url,
            "/media/sample_app/dependencytestingmodel/%s/image_4.jpg" % instance.pk)
        instance.image_2 = lenna_rect
        instance.save()
        self.assertEqual(instance.image_3.width, 100)
        self.assertEqual(instance.image_4.width, 150)
        # forward dependencies on django's FileFields will also do the cleanup
        self.assertTrue(not os.path.isfile(add_base(image_3_path)))
        self.assertTrue(not os.path.isfile(add_base(image_4_path)))
        instance.delete()
        lenna_rect.close()

    def test_dependency_error(self):
        instance = ImageTestingModel()
        image_1 = instance._meta.get_field('image_1')
        image_2 = instance._meta.get_field('image_2')
        self.assertRaises(ProgrammingError, image_2.manager.dependencies[0].set_field, image_1)

    def tearDown(self):
        remove_folder_content(add_base("media"))
        pass


